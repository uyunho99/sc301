"""
flow.py - 비즈니스 로직 레이어

Step 전이 로직, Transition/DecisionRule 평가, 프롬프트 생성.
Persona/Scenario 해석 및 slot extraction 기능 포함.

실제 그래프 구조 (2025-01 Ontology 기준):
- Step 전이: Step -[:TO]-> Step (1:N 가능, 분기점)
- 분기 평가: BRANCHING_RULES + CONSIDERS (primary) / RULE_CONDITION_MAP (fallback) + Condition 노드
- 가이드 선택: Step -[:GUIDED_BY]-> Guide (조건부 선택)
- 프로그램 추천: Step -[:RECOMMENDS]-> Program

최적화 내용:
- 전략 1: 메모리 캐싱 (Step, Persona, Scenario 데이터)
- 전략 6: LLM 스트리밍 응답
- 전략 8: 프롬프트 토큰 최적화
- 전략 4: 비동기 처리
"""

from __future__ import annotations
import logging
import time
import json
import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Generator
from dataclasses import dataclass, field

from neo4j import Driver
from openai import OpenAI, AsyncOpenAI

import re

try:
    from .state import ConversationState
    from .schema import (
        QUERY_ALL_PERSONAS,
        QUERY_PERSONA_BY_ID,
        QUERY_SCENARIO_BY_ID,
        QUERY_SCENARIO_START_STEP,
        QUERY_STEP_BY_ID,
        QUERY_STEP_CHECKS,
        QUERY_NEXT_STEPS_BY_TO,
        QUERY_NEXT_STEP_BY_LEADS_TO,
        QUERY_DECISION_RULE_CONDITIONS,
        QUERY_RULE_CONDITIONS_VIA_CONSIDERS,
        QUERY_HAS_CONSIDERS,
        QUERY_CHECKITEM_OPTIONS,
        BRANCHING_RULES,
        RULE_CONDITION_MAP,
        OR_LOGIC_RULES,
        GUIDE_SELECTION_RULES,
        AUTO_COMPUTABLE_SLOTS,
        CONDITIONAL_SKIP_RULES,
        SYSTEM_MANAGED_SLOTS,
        REGION_BUCKET_MAP,
        CHECKITEM_HINTS,
        QUERY_SCENARIO_ALL_CHECKS,
        CONSULTATION_KEYWORDS,
        CONSULTATION_SUBJECT_PATTERNS,
        CONSULTATION_SCORE_WEIGHTS,
        CONSULTATION_SCORE_THRESHOLD,
        CONSULTATION_RECOMMENDED_Q_MAP,
        CONSULTATION_TONE_STRATEGIES,
    )
except ImportError:
    from state import ConversationState
    from schema import (
        QUERY_ALL_PERSONAS,
        QUERY_PERSONA_BY_ID,
        QUERY_SCENARIO_BY_ID,
        QUERY_SCENARIO_START_STEP,
        QUERY_STEP_BY_ID,
        QUERY_STEP_CHECKS,
        QUERY_NEXT_STEPS_BY_TO,
        QUERY_NEXT_STEP_BY_LEADS_TO,
        QUERY_DECISION_RULE_CONDITIONS,
        QUERY_RULE_CONDITIONS_VIA_CONSIDERS,
        QUERY_HAS_CONSIDERS,
        QUERY_CHECKITEM_OPTIONS,
        BRANCHING_RULES,
        RULE_CONDITION_MAP,
        OR_LOGIC_RULES,
        GUIDE_SELECTION_RULES,
        AUTO_COMPUTABLE_SLOTS,
        CONDITIONAL_SKIP_RULES,
        SYSTEM_MANAGED_SLOTS,
        REGION_BUCKET_MAP,
        CHECKITEM_HINTS,
        QUERY_SCENARIO_ALL_CHECKS,
        CONSULTATION_KEYWORDS,
        CONSULTATION_SUBJECT_PATTERNS,
        CONSULTATION_SCORE_WEIGHTS,
        CONSULTATION_SCORE_THRESHOLD,
        CONSULTATION_RECOMMENDED_Q_MAP,
        CONSULTATION_TONE_STRATEGIES,
    )

logger = logging.getLogger(__name__)

# 같은 스텝에 머무는 최대 턴 수. 초과 시 미수집 항목을 "미응답"으로 채워 진행.
STALE_STEP_THRESHOLD = 3


@dataclass
class StepInfo:
    """Step 정보 컨테이너"""
    id: str
    desc: str
    step_type: str
    check_items: list[dict]
    guides: list[dict] = field(default_factory=list)
    programs: list[dict] = field(default_factory=list)
    reference_slots: list[str] = field(default_factory=list)


@dataclass
class TransitionResult:
    """전이 결과"""
    next_step_id: str | None
    via: str  # "branching", "to", "leadsTo", "end"
    debug: dict
    protocol_mode: str | None = None  # 분기로 인해 설정된 protocolMode


class FlowEngine:
    """상담 플로우 엔진"""

    def __init__(
        self,
        driver: Driver,
        openai_client: OpenAI | None = None,
        chat_model: str = "gpt-4o",
        async_openai_client: AsyncOpenAI | None = None,
        slot_extraction_model: str | None = None,
        max_response_tokens: int = 500,
        consultation_scoring_mode: str = "hybrid",
    ):
        self.driver = driver
        self.openai = openai_client
        self.chat_model = chat_model
        self.async_openai = async_openai_client

        self.slot_extraction_model = slot_extraction_model or chat_model
        self.max_response_tokens = max_response_tokens
        self.consultation_scoring_mode = consultation_scoring_mode  # "hybrid" | "llm" | "off"

        # 메모리 캐시 (전략 1)
        self._step_cache: dict[str, StepInfo] = {}
        self._persona_cache: dict[str, dict] = {}
        self._scenario_cache: dict[str, dict] = {}
        self._step_checks_cache: dict[str, list[dict]] = {}
        self._all_personas_cache: list[dict] | None = None
        self._cache_timestamps: dict[str, float] = {}
        self._cache_ttl: int = 300  # 5분

        # Condition 캐시 (DB에서 로드한 Condition 노드)
        self._condition_cache: dict[str, dict] = {}

        # CONSIDERS 관련 캐시
        self._rule_conditions_cache: dict[str, list[dict]] = {}
        self._has_considers: bool | None = None

    # =========================================================================
    # 캐시 유틸리티 (전략 1)
    # =========================================================================

    def _is_cache_valid(self, cache_key: str) -> bool:
        if cache_key not in self._cache_timestamps:
            return False
        return (time.time() - self._cache_timestamps[cache_key]) < self._cache_ttl

    def _set_cache_timestamp(self, cache_key: str) -> None:
        self._cache_timestamps[cache_key] = time.time()

    def clear_cache(self) -> None:
        self._step_cache.clear()
        self._persona_cache.clear()
        self._scenario_cache.clear()
        self._step_checks_cache.clear()
        self._all_personas_cache = None
        self._cache_timestamps.clear()
        self._condition_cache.clear()
        self._rule_conditions_cache.clear()
        self._has_considers = None

    # =========================================================================
    # Persona/Scenario Resolution (전략 1: 캐싱 적용)
    # =========================================================================

    def get_all_personas(self) -> list[dict]:
        cache_key = "_all_personas"
        if self._all_personas_cache is not None and self._is_cache_valid(cache_key):
            return self._all_personas_cache

        with self.driver.session() as session:
            result = session.run(QUERY_ALL_PERSONAS)
            self._all_personas_cache = [dict(r) for r in result]
            self._set_cache_timestamp(cache_key)
            return self._all_personas_cache

    def get_persona(self, persona_id: str) -> dict | None:
        cache_key = f"persona_{persona_id}"
        if persona_id in self._persona_cache and self._is_cache_valid(cache_key):
            return self._persona_cache[persona_id]

        with self.driver.session() as session:
            result = session.run(QUERY_PERSONA_BY_ID, personaId=persona_id)
            record = result.single()
            if record:
                self._persona_cache[persona_id] = dict(record)
                self._set_cache_timestamp(cache_key)
                return self._persona_cache[persona_id]
            return None

    def get_scenario(self, scenario_id: str) -> dict | None:
        cache_key = f"scenario_{scenario_id}"
        if scenario_id in self._scenario_cache and self._is_cache_valid(cache_key):
            return self._scenario_cache[scenario_id]

        with self.driver.session() as session:
            result = session.run(QUERY_SCENARIO_BY_ID, scenarioId=scenario_id)
            record = result.single()
            if record:
                self._scenario_cache[scenario_id] = dict(record)
                self._set_cache_timestamp(cache_key)
                return self._scenario_cache[scenario_id]
            return None

    def resolve_persona_scenario(
        self,
        state: ConversationState,
        user_text: str
    ) -> ConversationState:
        """첫 턴에서 사용자 발화 기반으로 Persona/Scenario 추론 및 할당.

        Disambiguation flow:
        - Turn 1: 모호하면 state.persona_disambiguation 저장 후 반환
                  (persona_id/scenario_id/current_step_id 미할당)
        - Turn 2: 원본+답변 합산 텍스트로 재분류 → persona 확정
        """
        if state.is_started():
            return state

        # ── Turn 2: disambiguation 해소 ──
        if state.persona_disambiguation is not None:
            combined = (
                state.persona_disambiguation["original_text"] + " " + user_text
            )
            personas = self.get_all_personas()
            if personas:
                state.persona_id = self._infer_persona(combined, personas)
            state.persona_disambiguation = None
            # → 아래 scenario/step 할당으로 fall-through

        # ── Turn 1: 첫 페르소나 판별 ──
        if not state.persona_id:
            personas = self.get_all_personas()
            if not personas:
                logger.warning("등록된 Persona가 없음")
                return state

            if self.openai and len(personas) > 1:
                scores = self._score_personas(user_text, personas)

                if (len(scores) >= 2
                        and scores[0]["score"] > 0
                        and scores[0]["score"] - scores[1]["score"]
                            <= self.PERSONA_AMBIGUITY_THRESHOLD):
                    # 모호 → 확인 질문 저장, persona 미확정 상태로 반환
                    pair = tuple(sorted([scores[0]["id"], scores[1]["id"]]))
                    question = self.PERSONA_DISAMBIGUATION_QUESTIONS.get(
                        pair, self.DEFAULT_DISAMBIGUATION_QUESTION
                    )
                    state.persona_disambiguation = {
                        "original_text": user_text,
                        "candidates": scores[:3],
                        "question": question,
                    }
                    logger.info(
                        f"Persona 모호: {scores[0]} vs {scores[1]}, "
                        f"확인 질문 요청"
                    )
                    return state  # persona_id = None 유지

                # 명확 → 바로 할당
                state.persona_id = (
                    scores[0]["id"] if scores and scores[0]["score"] > 0
                    else personas[0]["personaId"]
                )
            else:
                state.persona_id = personas[0]["personaId"]

        # ── Scenario & Step 할당 (공통) ──
        if state.persona_id and not state.scenario_id:
            persona = self.get_persona(state.persona_id)
            if persona and persona.get("scenarios"):
                state.scenario_id = persona["scenarios"][0]["id"]

        if state.scenario_id and not state.current_step_id:
            with self.driver.session() as session:
                result = session.run(
                    QUERY_SCENARIO_START_STEP, scenarioId=state.scenario_id
                )
                record = result.single()
                if record:
                    state.current_step_id = record["stepId"]

        return state

    # ── Persona disambiguation 설정 ──
    # 상위 2개 페르소나 점수차가 이 값 이하이면 확인 질문
    PERSONA_AMBIGUITY_THRESHOLD = 1

    # 페르소나 쌍별 확인 질문 (키는 정렬된 튜플)
    PERSONA_DISAMBIGUATION_QUESTIONS: dict[tuple[str, str], str] = {
        ("lipoCustomer", "slimBody"): (
            "지방이식에 관심이 있으시군요! "
            "혹시 체형이 마른 편이시거나 채취할 지방이 충분할지 걱정이 되시나요, "
            "아니면 지방흡입과 이식을 함께 고려하고 계신가요?"
        ),
    }
    DEFAULT_DISAMBIGUATION_QUESTION = (
        "좀 더 정확한 상담을 위해 여쭤볼게요. 어떤 부분이 가장 고민이신가요?"
    )

    # 페르소나 키워드 매핑 (전략 12: LLM 호출 제거)
    # RED = 판단기준 문서 최우선 키워드 그룹
    PERSONA_KEYWORDS: dict[str, list[str]] = {
        "slimBody": [
            # 기존
            "슬림", "마른", "체형", "체지방", "다이어트", "복부", "팔뚝", "허벅지", "바디", "체중",
            # RED: 지방이식·채취 관련
            "지방이식", "지방주입", "fat grafting", "fat transfer", "채취", "채취량",
            "생착", "생착률", "도너부위", "채취 부위", "뺄 데", "지방이 없어서",
            # RED: 체지방/체형 관련
            "체지방 부족", "체지방률", "저체중", "근육량", "벌크업",
            "살찌우기", "증량", "벌크", "체중 늘리기",
            # RED: 배경/상황 (확증)
            "운동선수", "바디프로필", "피트니스", "보디빌딩",
            "출산", "산후", "모유수유", "산후 다이어트",
            "트랜스젠더", "트랜스", "호르몬", "hrt",
            # RED: 적합성 판단 표현
            "제 몸에도 가능", "대안", "가능 여부",
        ],
        "lipoCustomer": [
            # 기존
            "지방흡입", "지방이식", "리포", "흡입",
            # RED: 시술 형태(복합)
            "람스", "바디라인", "라인 정리", "fat transfer", "빼고 채우는",
            # 효과/타이밍
            "효과 언제", "안정화", "붓기 빠지면",
            # 리스크/부작용
            "울퉁불퉁", "비대칭", "재수술 위험",
            # 비용/가성비
            "가성비", "비용 대비", "가격 차이", "추가 비용",
            # 방식 비교 (핵심 트리거)
            "줄기세포", "svf", "prp", "농축", "일반 지방이식", "장단점", "효과 차이",
            # 빠른 예약/행동 의지
            "바로 상담", "빨리 진행", "이번 주", "다음 주",
        ],
        "skinTreatment": [
            # 기존
            "피부", "레이저", "보톡스", "필러", "리프팅", "피부과", "여드름", "주름", "안티에이징",
            # RED: 목표/부위
            "팔자주름", "팔자", "볼 꺼짐", "볼살", "중안부",
            "나이 들어 보임", "동안", "어려 보이고 싶",
            # RED: 기존 경험
            "필러 해봤", "보톡스 해봤", "효과가 금방 빠졌",
            # 유지/효과
            "오래 유지", "지속", "한 번에", "리터치", "재시술", "다시 꺼짐",
            # 안전/회복 (우선순위 트리거)
            "안전", "회복기간", "붓기", "멍", "통증", "일상생활",
            # 설명 방식 선호
            "쉽게 설명", "직관적", "차이가 뭐예요",
        ],
        "longDistance": [
            # 기존
            "원거리", "타지역", "해외", "지방거주", "교통", "유학",
            # RED: 해외 체류/이동
            "캐나다", "토론토", "미국", "일본", "중국", "호주", "영국",
            "출국", "입국", "비행기", "항공", "시차", "해외번호",
            # RED: 일정/시간 관리 (핵심 트리거)
            "방문 기간", "체류 기간", "당일", "하루 만에", "원데이",
            "내원 횟수", "몇 번", "방문 횟수", "빠른 일정",
            # 회복/이동 가능 시점
            "비행기 타도 되나요", "장거리 이동", "출국 전",
            # 국내 원거리 지역
            "부산", "대구", "대전", "광주", "제주", "강원",
        ],
        "revisionFatigue": [
            # 기존 ("가슴" 제거 — 가슴성형 챗봇에서 너무 범용적이라 P5 과대평가 유발)
            "재수술", "부작용", "재교정", "불만족", "수정", "보형물",
            # RED: 과거 수술/재수술 맥락
            "리비전", "이전 수술", "기존 보형물", "몇 년 전 수술",
            # RED: 제거/교체 의도 ("빼고 싶" → "빼고" 로 활용형 대응)
            "제거", "완전 제거", "빼고", "교체", "보형물 종류 변경",
            # RED: 리스크/합병증 민감 (강한 확증)
            "석회화", "괴사", "구형구축", "파열", "염증", "피막", "캡슐렉토미",
            # RED: 모양/비대칭/사이즈 재설정
            "비대칭", "처짐", "모양 교정", "사이즈 줄이기", "사이즈 키우기",
            # 촉감/자연스러움/거부감 ("딱딱함" → "딱딱" 으로 활용형 대응)
            "이물감", "딱딱", "촉감", "심리적 거부",
            # 흉터/노출 회피
            "흉터", "비노출", "절개 위치",
            # 원스텝 선호
            "원스텝", "한번에 끝", "최소 횟수",
        ],
        "P1_BreastConsult": ["가슴", "유방", "브레스트", "가슴성형", "가슴확대", "가슴축소"],
        "P2_FaceConsult": ["코", "눈", "얼굴", "안면", "윤곽", "턱", "이마", "쌍꺼풀", "코성형"],
    }

    # 복합 신호 보너스 규칙 — 특정 키워드 조합이 동시 출현 시 보너스 점수 부여
    # 판별 포인트 기반: 경계 케이스 구분력 강화
    PERSONA_SIGNAL_RULES: dict[str, list[dict]] = {
        "slimBody": [
            # P1 핵심: "재료(지방) 부족" 인지가 먼저
            {"signals": ["지방이식", "마른"], "bonus": 3},
            {"signals": ["지방이식", "채취"], "bonus": 3},
            {"signals": ["체지방", "부족"], "bonus": 3},
            {"signals": ["체지방", "낮"], "bonus": 2},
            {"signals": ["증량", "지방이식"], "bonus": 2},
        ],
        "lipoCustomer": [
            # P2 핵심: 흡입+이식 복합, 3종세트 질문
            {"signals": ["흡입", "이식"], "bonus": 3},
            {"signals": ["줄기세포", "지방이식"], "bonus": 3},
            {"signals": ["비용 대비", "효과"], "bonus": 2},
        ],
        "skinTreatment": [
            # P3 핵심: 부위+자연+유지, 안전 최우선
            {"signals": ["팔자", "볼"], "bonus": 3},
            {"signals": ["자연스럽", "유지"], "bonus": 2},
            {"signals": ["필러", "보톡스"], "bonus": 2},
            {"signals": ["안전", "회복"], "bonus": 2},
        ],
        "longDistance": [
            # P4 핵심: 해외/원거리 + 일정 제약
            {"signals": ["해외", "일정"], "bonus": 3},
            {"signals": ["유학", "한국"], "bonus": 3},
            {"signals": ["체류", "기간"], "bonus": 3},
            {"signals": ["출국", "비행기"], "bonus": 3},
            {"signals": ["내원", "횟수"], "bonus": 2},
        ],
        "revisionFatigue": [
            # P5 핵심: 반드시 "재수술/과거 수술 이력"이 있어야 함
            {"signals": ["재수술", "이물감"], "bonus": 4},
            {"signals": ["재수술", "가슴"], "bonus": 4},
            {"signals": ["보형물", "제거"], "bonus": 4},
            {"signals": ["보형물", "구형구축"], "bonus": 4},
            {"signals": ["이전 수술", "가슴"], "bonus": 4},
            {"signals": ["석회화", "괴사"], "bonus": 3},
            # 보형물 + 불만/행동 표현 (촉감 불만, 제거 의도)
            {"signals": ["보형물", "딱딱"], "bonus": 3},
            {"signals": ["보형물", "빼고"], "bonus": 3},
        ],
    }

    # P5 필수 확증 키워드 — 이 중 하나라도 없으면 P5 점수 감산
    # 판별 포인트: "P5는 반드시 '재수술/과거 수술 이력'이 있어야 함"
    _P5_REQUIRED_SIGNALS = [
        "재수술", "재교정", "리비전", "이전 수술", "기존 보형물",
        "몇 년 전 수술", "보형물", "제거", "교체", "구형구축",
        "이물감", "석회화", "괴사", "피막",
    ]

    def _score_personas(self, user_text: str, personas: list[dict]) -> list[dict]:
        """전체 Persona 점수 산출.

        Returns:
            [{"id": persona_id, "score": int}, ...] score 내림차순 정렬.
        """
        text_lower = user_text.lower()
        valid_ids = {p["personaId"] for p in personas}
        results = []

        for persona_id, keywords in self.PERSONA_KEYWORDS.items():
            if persona_id not in valid_ids:
                continue
            # 기본 점수: 키워드 매칭 카운트
            score = sum(1 for kw in keywords if kw in text_lower)

            # 복합 신호 보너스
            if persona_id in self.PERSONA_SIGNAL_RULES:
                for rule in self.PERSONA_SIGNAL_RULES[persona_id]:
                    if all(sig in text_lower for sig in rule["signals"]):
                        score += rule["bonus"]

            # P5 필수 확증: 재수술/과거 이력 관련 키워드가 하나도 없으면 감산
            if persona_id == "revisionFatigue":
                if not any(s in text_lower for s in self._P5_REQUIRED_SIGNALS):
                    score = max(0, score - 5)

            results.append({"id": persona_id, "score": score})

        results.sort(key=lambda x: x["score"], reverse=True)
        return results

    def _infer_persona(self, user_text: str, personas: list[dict]) -> str:
        """키워드 + 복합 신호 매칭으로 사용자 발화에 맞는 Persona 추론 (전략 12)"""
        scores = self._score_personas(user_text, personas)
        if scores and scores[0]["score"] > 0:
            return scores[0]["id"]
        return personas[0]["personaId"]

    # =========================================================================
    # 자동 계산 / 조건부 스킵 (전략 16)
    # =========================================================================

    def auto_compute_slots(self, state: ConversationState) -> list[str]:
        """
        다른 Slot 값으로부터 자동 계산 가능한 Slot을 계산하여 state에 저장.
        새로 계산된 slot 이름 리스트를 반환.
        """
        computed = []

        for slot_name, rule in AUTO_COMPUTABLE_SLOTS.items():
            # 이미 값이 있으면 스킵
            if state.is_slot_filled(slot_name):
                continue

            # 필요한 선행 Slot이 모두 있는지 확인
            requires = rule["requires"]
            missing = [r for r in requires if not state.is_slot_filled(r)]
            if missing:
                continue

            # 계산 함수 호출
            compute_fn = getattr(self, f'_{rule["compute"]}', None)
            if compute_fn:
                value = compute_fn(state)
                if value is not None:
                    state.set_slot(slot_name, value)
                    computed.append(slot_name)
                    logger.info(f"Auto-computed {slot_name} = {value}")

        return computed

    def _compute_bmi(self, state: ConversationState) -> float | None:
        """
        bodyInfo에서 키/체중 추출 → BMI 계산.
        bodyInfo 형식 예: "170cm 65kg", "키 170 몸무게 65", "170/65" 등
        """
        body_info = state.get_slot("bodyInfo")
        if body_info is None:
            return None

        body_str = str(body_info)

        # 숫자 추출 패턴
        height = None
        weight = None

        # 패턴 1: "170cm 65kg" 또는 "170 cm 65 kg"
        cm_match = re.search(r'(\d+(?:\.\d+)?)\s*(?:cm|센치|센티)', body_str, re.IGNORECASE)
        kg_match = re.search(r'(\d+(?:\.\d+)?)\s*(?:kg|킬로)', body_str, re.IGNORECASE)

        if cm_match:
            height = float(cm_match.group(1))
        if kg_match:
            weight = float(kg_match.group(1))

        # 패턴 2: "키 170 몸무게 65"
        if height is None:
            h_match = re.search(r'키\s*[:：]?\s*(\d+(?:\.\d+)?)', body_str)
            if h_match:
                height = float(h_match.group(1))
        if weight is None:
            w_match = re.search(r'(?:몸무게|체중)\s*[:：]?\s*(\d+(?:\.\d+)?)', body_str)
            if w_match:
                weight = float(w_match.group(1))

        # 패턴 3: "170/65" 또는 "170, 65" (순서: 키/체중)
        if height is None and weight is None:
            pair_match = re.findall(r'(\d+(?:\.\d+)?)', body_str)
            if len(pair_match) >= 2:
                nums = [float(n) for n in pair_match[:2]]
                # 키(100 이상)와 체중(100 미만) 구분
                if nums[0] >= 100 and nums[1] < 100:
                    height, weight = nums[0], nums[1]
                elif nums[1] >= 100 and nums[0] < 100:
                    height, weight = nums[1], nums[0]

        # bodyInfo가 이미 float (체중만 저장된 경우) 처리
        if height is None and weight is None:
            try:
                val = float(body_str)
                # 100 이상이면 키, 미만이면 체중으로 추정 (불완전)
                # 이 경우 BMI 계산 불가
                return None
            except (ValueError, TypeError):
                pass

        if height and weight and height > 0:
            height_m = height / 100.0 if height > 3 else height  # cm→m 변환
            bmi = round(weight / (height_m ** 2), 1)
            logger.info(f"BMI 계산: {height}cm / {weight}kg = {bmi}")
            return bmi

        return None

    def _compute_region_bucket(self, state: ConversationState) -> str | None:
        """
        residenceCountry + domesticDistrict → regionBucket 자동 매핑.
        """
        country = state.get_slot("residenceCountry")
        if country is None:
            return None

        country_str = str(country).strip()

        # 해외 거주
        if country_str.upper() == "ABROAD" or country_str in ("해외", "외국"):
            return "ABROAD"

        # 국내: domesticDistrict → S1~S6
        district = state.get_slot("domesticDistrict")
        if district is None:
            return None

        district_str = str(district).strip()

        # 정확 매칭
        if district_str in REGION_BUCKET_MAP:
            return REGION_BUCKET_MAP[district_str]

        # 부분 매칭 (예: "서울특별시" → "서울")
        for key, bucket in REGION_BUCKET_MAP.items():
            if key in district_str:
                return bucket

        # 매칭 실패시 기본값 없음 (수동 확인 필요)
        logger.warning(f"regionBucket 매핑 실패: country={country_str}, district={district_str}")
        return None

    def should_skip_check_item(
        self,
        var_name: str,
        state: ConversationState
    ) -> bool:
        """
        조건부 스킵: 선행 Slot 값에 따라 이 CheckItem을 건너뛸 수 있는지 확인.
        True면 물어보지 않아도 됨.
        """
        # 시스템 관리 Slot은 항상 스킵 (물어보면 안 됨)
        if var_name in SYSTEM_MANAGED_SLOTS:
            return True

        # 조건부 스킵 규칙 확인
        if var_name in CONDITIONAL_SKIP_RULES:
            rule = CONDITIONAL_SKIP_RULES[var_name]
            when_conditions = rule["when"]

            # 모든 조건이 만족해야 스킵
            all_met = True
            for cond_var, cond_val in when_conditions.items():
                actual = state.get_slot(cond_var)
                if actual is None:
                    # 선행 정보가 아직 없으면 스킵 판단 불가 → 일단 스킵하지 않음
                    all_met = False
                    break
                actual_lower = str(actual).strip().lower()
                # cond_val이 리스트면 any 매칭, 단일 값이면 == 비교
                if isinstance(cond_val, list):
                    if actual_lower not in [str(v).strip().lower() for v in cond_val]:
                        all_met = False
                        break
                else:
                    if actual_lower != str(cond_val).strip().lower():
                        all_met = False
                        break

            if all_met:
                logger.info(f"조건부 스킵: {var_name} (조건: {when_conditions})")
                return True

        return False

    # =========================================================================
    # Step Navigation (전략 1: 캐싱 적용)
    # =========================================================================

    def get_step(self, step_id: str) -> StepInfo | None:
        """Step 정보 조회 (캐싱) - Guide, Program, ReferenceSlot 포함"""
        cache_key = f"step_{step_id}"
        if step_id in self._step_cache and self._is_cache_valid(cache_key):
            return self._step_cache[step_id]

        with self.driver.session() as session:
            result = session.run(QUERY_STEP_BY_ID, stepId=step_id)
            record = result.single()
            if not record:
                return None

            # check_items에서 null 항목 제거
            check_items = [ci for ci in (record["checkItems"] or []) if ci.get("id")]
            guides = [g for g in (record["guides"] or []) if g.get("id")]
            programs = [p for p in (record["programs"] or []) if p.get("id")]
            ref_slots = [r for r in (record["referenceSlots"] or []) if r]

            # stepType 결정: DB의 type 필드 또는 Step ID prefix로 추론
            step_type = record.get("stepType") or ""
            if not step_type:
                step_type = self._infer_step_type(step_id)

            step_info = StepInfo(
                id=record["stepId"],
                desc=record["desc"] or "",
                step_type=step_type,
                check_items=check_items,
                guides=guides,
                programs=programs,
                reference_slots=ref_slots,
            )
            self._step_cache[step_id] = step_info
            self._set_cache_timestamp(cache_key)
            return step_info

    def _infer_step_type(self, step_id: str) -> str:
        """Step ID에서 타입 추론 (DB에 stepType이 null인 경우)"""
        step_id_lower = step_id.lower()
        if "collect" in step_id_lower or "precollect" in step_id_lower:
            return "collect"
        elif "asklifestyle" in step_id_lower or "askdetail" in step_id_lower or "asksurgery" in step_id_lower or "askmedical" in step_id_lower:
            return "ask"
        elif "informsurg" in step_id_lower or "informinfo" in step_id_lower:
            return "inform"
        elif "confirm" in step_id_lower:
            return "confirm"
        elif "finalize" in step_id_lower:
            return "finalize"
        return "collect"  # 기본값

    def _is_auto_transition_step(self, step_id: str) -> bool:
        """사용자 입력 없이 자동 전이해야 하는 스텝인지 확인 (inform 등)"""
        step = self.get_step(step_id)
        if not step:
            return False
        return step.step_type in ("inform",)

    def get_step_checks(self, step_id: str) -> list[dict]:
        """Step의 CheckItem 목록 조회 (캐싱)"""
        cache_key = f"step_checks_{step_id}"
        if step_id in self._step_checks_cache and self._is_cache_valid(cache_key):
            return self._step_checks_cache[step_id]

        with self.driver.session() as session:
            result = session.run(QUERY_STEP_CHECKS, stepId=step_id)
            checks = [dict(r) for r in result]
            self._step_checks_cache[step_id] = checks
            self._set_cache_timestamp(cache_key)
            return checks

    def get_scenario_all_checks(self, scenario_id: str) -> list[dict]:
        """시나리오 전체 CheckItem 목록 조회 (ASKS_FOR 관계, 캐싱)"""
        cache_key = f"scenario_checks_{scenario_id}"
        if scenario_id in self._step_checks_cache and self._is_cache_valid(cache_key):
            return self._step_checks_cache[scenario_id]

        with self.driver.session() as session:
            result = session.run(QUERY_SCENARIO_ALL_CHECKS, scenarioId=scenario_id)
            checks = [dict(r) for r in result]
            self._step_checks_cache[scenario_id] = checks
            self._set_cache_timestamp(cache_key)
            return checks

    # =========================================================================
    # Step Transition (TO + BRANCHING_RULES 기반)
    # =========================================================================

    def next_step(self, state: ConversationState) -> TransitionResult:
        """
        다음 Step 결정.

        핵심 규칙:
        - 현재 Step의 필수 CheckItem이 아직 수집 안 됐으면 → 머무름 (질문 계속)
        - 분기점 Step에서 분기 조건에 필요한 slot이 없으면 → 머무름
        - 조건 충족 시 → 다음 Step으로 이동

        평가 순서:
        1. 현재 Step의 CheckItem 수집 완료 여부 확인
        2. BRANCHING_RULES에 해당 Step이 있으면 조건 평가
        3. TO 관계로 연결된 다음 Step
        4. leadsTo fallback (레거시)
        5. None (종료)
        """
        if not state.current_step_id:
            return TransitionResult(None, "end", {"reason": "current_step_id 없음"})

        step_id = state.current_step_id

        # 1. 현재 Step의 CheckItem 수집 완료 여부 확인
        #    inform 스텝은 사용자 입력 불필요 → 미수집이어도 통과
        #    그 외 스텝은 미수집이면 머무름
        if not self._is_auto_transition_step(step_id) and not self._are_step_checks_filled(step_id, state):
            return TransitionResult(
                None, "stay",
                {"reason": "필수 CheckItem 미수집", "stepId": step_id}
            )

        # 2. BRANCHING_RULES에서 분기 확인
        if step_id in BRANCHING_RULES:
            result = self._evaluate_branching_rules(step_id, state)
            if result:
                return result
            # 분기 규칙 매칭 실패 → "stay" 대신 TO 관계로 fallthrough
            # (slot 값이 예상과 다른 경우에도 진행 가능하도록)
            logger.warning(
                f"분기 규칙 매칭 실패, TO 관계로 fallback: step={step_id}"
            )

        # 3. TO 관계 기반 전이
        to_steps = self._get_to_steps(step_id)
        if to_steps:
            if len(to_steps) == 1:
                return TransitionResult(
                    to_steps[0]["nextStepId"],
                    "to",
                    {"singlePath": True}
                )
            else:
                # 다중 경로인데 BRANCHING_RULES에 없음 → 첫 번째로 이동
                return TransitionResult(
                    to_steps[0]["nextStepId"],
                    "to",
                    {"multiPath": True, "candidates": [s["nextStepId"] for s in to_steps]}
                )

        # 4. leadsTo fallback
        leads_to = self._get_leads_to(step_id)
        if leads_to:
            return TransitionResult(leads_to, "leadsTo", {"fallback": True})

        # 5. 종료
        return TransitionResult(None, "end", {"reason": "더 이상 전이 없음"})

    def _chain_through_empty_steps(self, state: ConversationState) -> list[str]:
        """
        연쇄 전이: 현재 스텝에 미수집 CheckItem이 없으면 자동으로 다음 스텝까지 진행.
        inform 스텝은 CheckItem 유무와 관계없이 자동 통과.
        최대 5회까지 (무한 루프 방지).

        Returns:
            건너뛴 inform 스텝 ID 리스트 (안내 내용 전달용)
        """
        skipped_inform_steps = []

        for _ in range(5):
            if not state.current_step_id:
                break

            # 자동 계산 가능한 Slot 산출 (체이닝 중에도 필요)
            self.auto_compute_slots(state)

            is_auto = self._is_auto_transition_step(state.current_step_id)

            # inform이 아닌 스텝: 미수집 CheckItem이 있으면 멈춤
            if not is_auto and not self._are_step_checks_filled(state.current_step_id, state):
                break

            # inform 스텝은 건너뛰되, 안내 내용을 기록
            if is_auto:
                skipped_inform_steps.append(state.current_step_id)

            # 다음 스텝으로 전이 시도
            chain = self.next_step(state)
            if chain.protocol_mode:
                state.set_slot("protocolMode", chain.protocol_mode)
            if chain.next_step_id:
                logger.info(f"연쇄 전이: {state.current_step_id} → {chain.next_step_id}")
                state.move_to_step(chain.next_step_id)
            else:
                break

        return skipped_inform_steps

    def _build_skipped_inform_context(
        self,
        skipped_steps: list[str],
        state: ConversationState
    ) -> str:
        """
        건너뛴 inform 스텝의 Guide/Program 안내 내용을 모아 프롬프트에 포함.
        LLM이 이 내용을 고객에게 반드시 전달하도록 지시.
        """
        if not skipped_steps:
            return ""

        parts = []
        for step_id in skipped_steps:
            step = self.get_step(step_id)
            if not step:
                continue
            guide_text = self._get_guide_text(step, state)
            program_text = self._get_program_text(step)
            section = f"### {step.desc or step_id}"
            if guide_text:
                section += f"\n{guide_text[:500]}"
            if program_text:
                section += f"\n{program_text}"
            if step.desc and not guide_text and not program_text:
                section += f"\n(안내 단계: {step.desc})"
            parts.append(section)

        if not parts:
            return ""

        return (
            "[아래 안내 내용을 반드시 고객에게 간략히 설명한 후, "
            "다음 질문으로 자연스럽게 이어가세요]\n\n"
            + "\n\n".join(parts)
        )

    def _handle_stale_step(self, state: ConversationState) -> None:
        """
        동일 스텝에 STALE_STEP_THRESHOLD 턴 이상 머물렀을 때 호출.
        미수집 CheckItem을 '미응답'으로 채워 다음 스텝으로 진행 가능하게 함.
        confirm/finalize 스텝은 제외 (필수 정보이므로).
        """
        step_id = state.current_step_id
        if not step_id:
            return

        step = self.get_step(step_id)
        if not step:
            return

        # 확인/마무리 단계의 핵심 정보(고객명, 전화번호 등)는 강제 진행 안 함
        if step.step_type in ("confirm", "finalize"):
            return

        checks = self.get_step_checks(step_id)
        for ci in (checks or []):
            vn = ci.get("variableName") or ci.get("name") or ci.get("id")
            if not vn:
                continue
            if state.is_slot_filled(vn):
                continue
            if self.should_skip_check_item(vn, state):
                continue
            if vn in AUTO_COMPUTABLE_SLOTS:
                continue
            # 미수집 항목을 "미응답"으로 채움
            state.set_slot(vn, "미응답")
            logger.info(f"Stale step 복구: {vn} = '미응답' (step={step_id})")

    def _are_step_checks_filled(self, step_id: str, state: ConversationState) -> bool:
        """
        현재 Step의 CHECKS CheckItem이 모두 수집되었는지 확인.

        조건부 스킵/시스템 관리 항목은 "수집된 것"으로 간주.
        자동 계산 가능 항목은 선행 데이터가 있으면 계산 시도.
        """
        checks = self.get_step_checks(step_id)
        if not checks:
            # CheckItem이 없는 Step (inform, finalize 등)은 통과
            return True

        for ci in checks:
            var_name = ci.get("variableName") or ci.get("name") or ci.get("id")
            if not var_name:
                continue

            # 이미 값이 있으면 OK
            if state.is_slot_filled(var_name):
                continue

            # 조건부 스킵 대상이면 OK (물어보지 않아도 됨)
            if self.should_skip_check_item(var_name, state):
                continue

            # 자동 계산 가능한 항목이면 계산 시도
            if var_name in AUTO_COMPUTABLE_SLOTS:
                self.auto_compute_slots(state)
                if state.is_slot_filled(var_name):
                    continue

            # 여기까지 왔으면 미수집 항목 존재
            return False
        return True

    def _get_to_steps(self, step_id: str) -> list[dict]:
        """TO 관계로 연결된 다음 Step 목록 조회"""
        with self.driver.session() as session:
            result = session.run(QUERY_NEXT_STEPS_BY_TO, stepId=step_id)
            return [dict(r) for r in result]

    def _get_leads_to(self, step_id: str) -> str | None:
        """leadsTo 관계로 연결된 다음 Step 조회 (레거시 호환)"""
        with self.driver.session() as session:
            result = session.run(QUERY_NEXT_STEP_BY_LEADS_TO, stepId=step_id)
            record = result.single()
            return record["nextStepId"] if record else None

    def _evaluate_branching_rules(
        self,
        step_id: str,
        state: ConversationState
    ) -> TransitionResult | None:
        """BRANCHING_RULES 기반 분기 조건 평가"""
        rules = BRANCHING_RULES[step_id]

        # priority DESC로 정렬
        sorted_rules = sorted(rules, key=lambda r: r.get("priority", 0), reverse=True)

        default_rule = None

        for rule in sorted_rules:
            if rule.get("isDefault"):
                default_rule = rule
                continue

            # DecisionRule 기반 평가
            if rule.get("ruleId"):
                if self._evaluate_rule_filtered(rule["ruleId"], state):
                    # protocolMode 설정이 필요한 경우
                    protocol = self._determine_protocol_mode(rule, state)
                    return TransitionResult(
                        rule["targetStepId"],
                        "branching",
                        {"transitionId": rule["transitionId"], "ruleId": rule["ruleId"]},
                        protocol_mode=protocol,
                    )
            # 직접 조건 평가 (ruleId 없이 conditionVar 지정)
            elif rule.get("conditionVar"):
                actual = state.get_slot(rule["conditionVar"])
                if actual is not None:
                    if self._compare_values(
                        str(actual),
                        rule.get("conditionOp", "="),
                        rule.get("conditionRef", "")
                    ):
                        return TransitionResult(
                            rule["targetStepId"],
                            "branching",
                            {"transitionId": rule["transitionId"], "directCondition": True},
                        )

        # Default transition
        if default_rule:
            return TransitionResult(
                default_rule["targetStepId"],
                "branching",
                {"transitionId": default_rule["transitionId"], "isDefault": True},
            )

        return None

    def _determine_protocol_mode(self, rule: dict, state: ConversationState) -> str | None:
        """분기 규칙에 따른 protocolMode 결정"""
        rule_id = rule.get("ruleId", "")

        # BMI 기반 분기 -> protocolMode 설정
        if rule_id == "ruleBodyFatHigh":
            return "STANDARD"
        elif rule_id == "ruleBodyFatLow":
            return "LOW-FAT"

        # 거주지 기반 분기 -> protocolMode 설정
        elif rule_id == "ruleRegionRemote":
            return "FULL"
        elif rule_id == "ruleRegionSemiRemote":
            return "SEMI-REMOTE"

        # 유방암/보형물 분기
        elif rule_id == "ruleCancerNone":
            return "STANDARD"
        elif rule_id == "ruleCancerConditional":
            return "CONDITIONAL"
        elif rule_id == "ruleCancerNotAllowed":
            return "NOT_ALLOWED"

        return None

    def _check_has_considers(self) -> bool:
        """DB에 CONSIDERS 관계가 존재하는지 확인 (1회 실행 후 캐싱)."""
        if self._has_considers is not None:
            return self._has_considers
        try:
            with self.driver.session() as session:
                result = session.run(QUERY_HAS_CONSIDERS)
                record = result.single()
                self._has_considers = bool(record and record["hasConsiders"])
        except Exception:
            self._has_considers = False
        logger.info("DB CONSIDERS support: %s", self._has_considers)
        return self._has_considers

    def _load_conditions_via_considers(self, rule_id: str) -> list[dict] | None:
        """
        CONSIDERS 관계로 DecisionRule의 Condition 로드.
        CONSIDERS 엣지가 없으면 None 반환 (fallback 필요 신호).
        """
        if rule_id in self._rule_conditions_cache:
            return self._rule_conditions_cache[rule_id]

        with self.driver.session() as session:
            result = session.run(
                QUERY_RULE_CONDITIONS_VIA_CONSIDERS,
                ruleId=rule_id,
            )
            record = result.single()
            if not record:
                return None

            conditions = record.get("conditions", [])
            # condId가 None인 항목 제거 (CONSIDERS 엣지 없는 경우 빈 collect)
            conditions = [c for c in conditions if c.get("condId")]
            if not conditions:
                return None

            self._rule_conditions_cache[rule_id] = conditions

            # 개별 Condition 캐시에도 등록
            for c in conditions:
                cid = c.get("condId")
                if cid and cid not in self._condition_cache:
                    self._condition_cache[cid] = c

            return conditions

    def _evaluate_rule_filtered(self, rule_id: str, state: ConversationState) -> bool:
        """
        DecisionRule 평가 (3-tier fallback).

        1. CONSIDERS 관계 (DB, 정확한 1:N 매핑)
        2. RULE_CONDITION_MAP (하드코딩 fallback)
        3. WHEN -> ConditionGroup -> HAS_CONDITION (레거시 fallback)
        """
        conditions = None

        # Tier 1: CONSIDERS (DB에 관계가 있으면 우선 사용)
        if self._check_has_considers():
            conditions = self._load_conditions_via_considers(rule_id)

        # Tier 2: RULE_CONDITION_MAP (하드코딩 fallback)
        if conditions is None:
            relevant_cond_ids = RULE_CONDITION_MAP.get(rule_id)
            if relevant_cond_ids:
                conditions = self._load_conditions(relevant_cond_ids)

        # Tier 3: WHEN -> ConditionGroup -> HAS_CONDITION (레거시)
        if conditions is None:
            return self._evaluate_rule_from_db(rule_id, state)

        if not conditions:
            return True  # 조건 없으면 통과

        # AND/OR 로직 결정
        results = [self._evaluate_condition(c, state) for c in conditions]

        if rule_id in OR_LOGIC_RULES:
            return any(results)
        return all(results)

    def _load_conditions(self, condition_ids: list[str]) -> list[dict]:
        """Condition 노드 로드 (캐싱)"""
        conditions = []
        missing_ids = []

        for cid in condition_ids:
            if cid in self._condition_cache:
                conditions.append(self._condition_cache[cid])
            else:
                missing_ids.append(cid)

        if missing_ids:
            with self.driver.session() as session:
                for cid in missing_ids:
                    result = session.run(
                        "MATCH (c:Condition {id: $condId}) "
                        "RETURN c.id AS condId, c.input AS input, c.op AS op, "
                        "c.ref AS ref, c.refType AS refType, c.missingPolicy AS missingPolicy",
                        condId=cid
                    )
                    record = result.single()
                    if record:
                        cond = dict(record)
                        self._condition_cache[cid] = cond
                        conditions.append(cond)

        return conditions

    def _evaluate_rule_from_db(self, rule_id: str, state: ConversationState) -> bool:
        """DB에서 DecisionRule 조건 로드 후 평가 (fallback)"""
        with self.driver.session() as session:
            result = session.run(QUERY_DECISION_RULE_CONDITIONS, ruleId=rule_id)
            record = result.single()

            if not record:
                return True

            logic = record.get("logic", "AND")
            conditions = record.get("conditions", [])

            if not conditions:
                return True

            results = [self._evaluate_condition(c, state) for c in conditions]

            if logic == "OR":
                return any(results)
            else:
                return all(results)

    def _evaluate_condition(self, condition: dict, state: ConversationState) -> bool:
        """단일 Condition 평가 (input/op/ref/refType 기반)"""
        input_var = condition.get("input")
        op = condition.get("op")
        ref = condition.get("ref")
        ref_type = condition.get("refType", "string")
        missing_policy = condition.get("missingPolicy", "UNKNOWN")

        actual_value = state.get_slot(input_var)

        # 값이 없을 때 정책 적용
        if actual_value is None:
            if missing_policy == "TRUE":
                return True
            elif missing_policy == "FALSE":
                return False
            else:  # UNKNOWN
                return False

        return self._compare_values(str(actual_value), op, ref, ref_type)

    def _compare_values(
        self,
        actual: str,
        op: str,
        ref: str,
        ref_type: str = "string"
    ) -> bool:
        """값 비교 연산 (DB에서 bool/int 등 다양한 타입이 올 수 있으므로 str 변환)"""
        # DB에서 bool, int 등으로 올 수 있으므로 안전하게 str 변환
        actual = str(actual) if actual is not None else ""
        ref = str(ref) if ref is not None else ""

        try:
            if ref_type == "number":
                actual_num = float(actual)
                ref_num = float(ref)
                if op == "<":
                    return actual_num < ref_num
                elif op == "<=":
                    return actual_num <= ref_num
                elif op == ">":
                    return actual_num > ref_num
                elif op == ">=":
                    return actual_num >= ref_num
                elif op in ("=", "=="):
                    return actual_num == ref_num
                elif op == "!=":
                    return actual_num != ref_num
            elif ref_type == "boolean":
                actual_bool = actual.lower() in ("true", "1", "yes")
                ref_bool = ref.lower() in ("true", "1", "yes")
                if op in ("=", "=="):
                    return actual_bool == ref_bool
                elif op == "!=":
                    return actual_bool != ref_bool
            else:  # string
                if op in ("=", "=="):
                    return actual.strip().lower() == ref.strip().lower()
                elif op == "!=":
                    return actual.strip().lower() != ref.strip().lower()
        except (ValueError, TypeError):
            # 숫자 변환 실패 시 문자열 비교
            if op in ("=", "=="):
                return actual == ref
            elif op == "!=":
                return actual != ref

        return False

    # =========================================================================
    # Guide Selection (조건부)
    # =========================================================================

    def select_guides(self, step_id: str, state: ConversationState, all_guides: list[dict]) -> list[dict]:
        """현재 상태에 따라 적절한 Guide 선택"""
        if not all_guides:
            return []

        # GUIDE_SELECTION_RULES에 해당 Step이 있으면 조건부 선택
        if step_id in GUIDE_SELECTION_RULES:
            rule = GUIDE_SELECTION_RULES[step_id]
            condition_var = rule["conditionVar"]
            current_value = state.get_slot(condition_var)

            if current_value and current_value in rule["mapping"]:
                allowed_ids = rule["mapping"][current_value]
                filtered = [g for g in all_guides if g.get("id") in allowed_ids]
                if filtered:
                    return filtered

        # 조건 매칭 안되면 전체 Guide 반환
        return all_guides

    # =========================================================================
    # Slot Extraction
    # =========================================================================

    def _get_checkitem_options(self, check_item_id: str) -> list[dict]:
        """CheckItem의 Option 목록 조회"""
        try:
            with self.driver.session() as session:
                result = session.run(QUERY_CHECKITEM_OPTIONS, checkItemId=check_item_id)
                return [dict(r) for r in result]
        except Exception:
            return []

    def _build_variable_desc(self, ci: dict, state: ConversationState) -> str | None:
        """CheckItem을 추출 프롬프트용 설명 문자열로 변환. 필터링 대상이면 None 반환."""
        var_name = ci.get("variableName") or ci.get("name") or ci.get("id")
        if not var_name:
            return None

        # AUTO_COMPUTABLE / SYSTEM_MANAGED / 조건부 스킵 대상 필터링
        if var_name in AUTO_COMPUTABLE_SLOTS:
            return None
        if var_name in SYSTEM_MANAGED_SLOTS:
            return None
        if self.should_skip_check_item(var_name, state):
            return None

        label = ci.get("name", var_name)
        dtype = ci.get("dataType", "string")

        # CheckItem 옵션(열거값) 조회
        options = self._get_checkitem_options(var_name)
        if options:
            opt_values = [o.get("value", o.get("optionId", "")) for o in options if o.get("value") or o.get("optionId")]
            return f"- {var_name}: {label} ({dtype}) [선택지: {', '.join(opt_values)}]"

        # CHECKITEM_HINTS로 추가 설명 제공
        hint = CHECKITEM_HINTS.get(var_name, "")
        if hint:
            return f"- {var_name}: {label} ({dtype}) — {hint}"

        return f"- {var_name}: {label} ({dtype})"

    def extract_slots(
        self,
        state: ConversationState,
        user_text: str,
        step_id: str | None = None
    ) -> ConversationState:
        """LLM으로 사용자 발화에서 CheckItem 값 추출.

        현재 스텝의 CheckItem을 추출하고, 다음 스텝(1개)의 항목은
        prefetch_slots에 별도 저장 (현재 스텝 응답에 노출되지 않음).
        분기점이거나 다음 스텝이 불확정이면 현재 스텝만 추출.
        """
        if not self.openai:
            logger.warning("OpenAI 클라이언트 없음, slot 추출 스킵")
            return state

        current_step = step_id or state.current_step_id
        if not current_step:
            return state

        # 현재 스텝의 CheckItem
        check_items = list(self.get_step_checks(current_step))

        # 현재 스텝 변수명 수집 (저장 시 분기 판단용)
        current_var_names = set()
        for ci in check_items:
            vn = ci.get("variableName") or ci.get("name") or ci.get("id")
            if vn:
                current_var_names.add(vn)

        # Next-step prefetch: n+1 CheckItem도 추출 대상에 추가 (prefetch_slots에 분리 저장)
        # - 분기점(BRANCHING_RULES)이면 다음 스텝이 불확정이므로 스킵
        # - TO 관계가 1개인 경우만 (다중 경로면 스킵)
        prefetch_var_names = set()
        if current_step not in BRANCHING_RULES:
            to_steps = self._get_to_steps(current_step)
            if len(to_steps) == 1:
                next_step_id = to_steps[0]["nextStepId"]
                next_checks = self.get_step_checks(next_step_id)
                current_ids = {ci.get("id") for ci in check_items if ci.get("id")}
                for ci in next_checks:
                    ci_id = ci.get("id")
                    if ci_id and ci_id not in current_ids:
                        vn = ci.get("variableName") or ci.get("name") or ci_id
                        if not state.is_slot_filled(vn):
                            prefetch_var_names.add(vn)
                            check_items.append(ci)
                            current_ids.add(ci_id)

        if not check_items:
            return state

        # AUTO_COMPUTABLE / SYSTEM_MANAGED / 스킵 대상 필터링 + 옵션 힌트 포함
        variables = []
        valid_var_names = set()
        for ci in check_items:
            desc = self._build_variable_desc(ci, state)
            if desc:
                var_name = ci.get("variableName") or ci.get("name") or ci.get("id")
                variables.append(desc)
                valid_var_names.add(var_name)

        if not variables:
            return state

        prompt = f"""가슴성형 상담 정보 추출. 사용자 발화에서 해당 항목의 값을 추출하세요.

규칙:
- 사용자가 전혀 언급하지 않은 항목은 반드시 null (JSON null, 문자열 "null" 금지)
- boolean 항목은 반드시 "true" 또는 "false" 문자열로 반환
- "없습니다", "없어요", "안 했어요", "처음입니다" 등 부정/없음 답변은 "없음"으로 추출 (null 아님!)
  예: "시술 받은 적 없습니다" → pastOps: "없음", pastOpsSite: "없음"
  예: "알레르기 없어요" → allergyHistory: "없음"
- 사용자가 "해당 없습니다", "상관없어요" 등 명시적으로 해당 없음을 말한 항목만 "해당없음"으로 추출
- 중요: 사용자가 언급하지 않은 항목을 "해당없음"으로 추출하지 마세요. 반드시 null로 반환하세요.

[추출 대상]
{chr(10).join(variables)}

[발화]
{user_text}

JSON 반환: {{"변수명": "값"}}"""

        try:
            response = self.openai.chat.completions.create(
                model=self.slot_extraction_model,
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
            )

            extracted = json.loads(response.choices[0].message.content)

            for key, value in extracted.items():
                # 유효한 변수명만 저장 (잘못된 키 방지)
                if key not in valid_var_names:
                    logger.debug(f"Slot 무시 (유효하지 않은 키): {key}")
                    continue
                # None 또는 빈 문자열은 저장하지 않음
                if value is None:
                    continue
                if isinstance(value, str) and not value.strip():
                    continue
                # "null" 문자열은 JSON null과 동일하게 무시
                if isinstance(value, str) and value.strip().lower() == "null":
                    continue
                # 현재 스텝 항목 → slots, n+1 항목 → prefetch_slots
                if key in prefetch_var_names:
                    state.set_prefetch_slot(key, value)
                else:
                    state.set_slot(key, value)

            logger.debug(f"Extracted slots: {extracted}")

        except Exception as e:
            logger.error(f"Slot 추출 실패: {e}")

        return state

    # =========================================================================
    # 상담 Persona 스코어링 (톤/전략 레이어 — Flow 무관)
    # =========================================================================

    def score_consultation_persona(
        self, state: ConversationState, user_text: str
    ) -> None:
        """매 턴 상담 Persona 신호를 누적하고, threshold 초과 시 확정."""
        if self.consultation_scoring_mode == "off":
            return
        if state.consultation_persona:
            return  # 이미 확정됨

        # 초기화
        if not state.consultation_scores:
            state.consultation_scores = {
                "desire": 0.0, "body": 0.0, "social": 0.0, "service": 0.0,
            }

        # 스코어링 모드별 분기
        if self.consultation_scoring_mode == "llm":
            turn_scores = self._llm_score_consultation(user_text, state)
        else:  # hybrid
            rule_scores = self._rule_score_consultation(user_text)
            total_signal = sum(rule_scores.values())
            if total_signal >= 2.0:
                turn_scores = rule_scores
            else:
                turn_scores = self._llm_score_consultation(user_text, state)

        # 추천질문 매칭 보너스
        rq_scores = self._check_recommended_q_match(user_text)
        for persona, score in rq_scores.items():
            turn_scores[persona] = turn_scores.get(persona, 0.0) + score

        # 누적
        for persona in ("desire", "body", "social", "service"):
            state.consultation_scores[persona] += turn_scores.get(persona, 0.0)

        # 신호 로그
        state.consultation_signals.append({
            "turn": len(state.history),
            "mode": self.consultation_scoring_mode,
            "scores": dict(turn_scores),
            "cumulative": dict(state.consultation_scores),
        })

        # threshold 체크 → 확정
        threshold = CONSULTATION_SCORE_THRESHOLD
        top_persona = max(
            state.consultation_scores,
            key=lambda p: state.consultation_scores[p],
        )
        if state.consultation_scores[top_persona] >= threshold:
            state.consultation_persona = top_persona
            logger.info(
                f"상담 Persona 확정: {top_persona} "
                f"(score={state.consultation_scores[top_persona]:.1f})"
            )
        state._touch()

    def _rule_score_consultation(self, user_text: str) -> dict[str, float]:
        """Rule 기반: 키워드 매칭 + 질문 주어 패턴."""
        scores: dict[str, float] = {}
        text_lower = user_text.lower()
        kw_weight = CONSULTATION_SCORE_WEIGHTS["keyword_match"]
        subj_weight = CONSULTATION_SCORE_WEIGHTS["subject_pattern"]

        for persona, keywords in CONSULTATION_KEYWORDS.items():
            kw_count = sum(1 for kw in keywords if kw in text_lower)
            scores[persona] = kw_count * kw_weight

        for persona, patterns in CONSULTATION_SUBJECT_PATTERNS.items():
            for pattern in patterns:
                if re.search(pattern, user_text):
                    scores[persona] = scores.get(persona, 0.0) + subj_weight
                    break  # 패턴 당 1회만

        return scores

    def _llm_score_consultation(
        self, user_text: str, state: ConversationState
    ) -> dict[str, float]:
        """LLM-as-Judge: 경량 모델로 4차원 스코어 반환."""
        if not self.openai:
            return {}

        multiplier = CONSULTATION_SCORE_WEIGHTS["llm_score_multiplier"]
        system_prompt = """아래 사용자 발화를 분석하여 4개 상담 Persona 차원별 신호 강도(0~3)를 JSON으로 반환하세요.
결과는 반드시 {"desire": 0, "body": 0, "social": 0, "service": 0} 형태여야 합니다. 숫자만 포함하세요.

Desire fit: 감정·자기애·심리적 만족 중심. 키워드: "괜찮을까요?", "후회", "마음", "신뢰", "안심", "불안"
Body fit: 신체 균형·건강미·웰빙. 키워드: "체형", "밸런스", "운동", "유지", "라인", "균형"
Social fit: 타인 시선·이미지 관리. 키워드: "티 나다", "주변 반응", "사진", "사람들", "이미지"
Service fit: 서비스 품질·효율·시스템. 키워드: "비용 대비", "사후관리", "프로세스", "전문성", "시스템"
"""
        try:
            response = self.openai.chat.completions.create(
                model=self.slot_extraction_model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_text},
                ],
                response_format={"type": "json_object"},
                max_completion_tokens=100,
            )
            raw = json.loads(response.choices[0].message.content)
            return {
                persona: float(raw.get(persona, 0)) * multiplier
                for persona in ("desire", "body", "social", "service")
            }
        except Exception as e:
            logger.warning(f"상담 Persona LLM 스코어링 실패: {e}")
            return {}

    def _check_recommended_q_match(self, user_text: str) -> dict[str, float]:
        """추천질문 매칭: 사용자가 추천질문을 선택했는지 부분 문자열 매칭."""
        scores: dict[str, float] = {}
        rq_weight = CONSULTATION_SCORE_WEIGHTS["recommended_q"]
        for question, persona in CONSULTATION_RECOMMENDED_Q_MAP.items():
            if question in user_text:
                scores[persona] = scores.get(persona, 0.0) + rq_weight
        return scores

    # =========================================================================
    # Prompt Building (전략 8: 간소화 + Guide/Program 포함)
    # =========================================================================

    def _build_persona_context(self, state: ConversationState) -> str:
        """페르소나 + 시나리오 + 상담톤 컨텍스트 문자열 생성"""
        parts = ["당신은 가슴성형(줄기세포 지방이식, 보형물 등) 전문 상담 챗봇입니다. 모든 상담은 여성 고객 대상 가슴성형 맥락에서 진행됩니다."]

        if state.persona_id:
            persona = self.get_persona(state.persona_id)
            if persona:
                name = persona.get("name", state.persona_id)
                desc = persona.get("desc", "")
                parts.append(f"페르소나: {name}")
                if desc:
                    parts.append(f"설명: {desc}")

        if state.scenario_id:
            scenario = self.get_scenario(state.scenario_id)
            if scenario:
                s_name = scenario.get("name", state.scenario_id)
                s_domain = scenario.get("domain", "")
                parts.append(f"시나리오: {s_name}" + (f" ({s_domain})" if s_domain else ""))

        # 상담 Persona 톤 주입
        if state.consultation_persona:
            tone = CONSULTATION_TONE_STRATEGIES.get(state.consultation_persona)
            if tone:
                parts.append("")
                parts.append("## 상담 톤 지침")
                parts.append(f"전략: {tone['strategy']}")
                parts.append(f"유도 멘트: {tone['guide_tone']}")
                parts.append(f"트리거 표현: {', '.join(tone['trigger_expressions'])}")
                parts.append(f"절대 금기 표현: {', '.join(tone['taboo'])}")

        return "\n".join(parts)

    def build_step_prompt(
        self,
        step_id: str,
        state: ConversationState,
        rag_context: str = ""
    ) -> str:
        """해당 Step의 CheckItem/Guide/Program 기반으로 시스템 프롬프트 생성."""
        step = self.get_step(step_id)
        if not step:
            return "시스템 오류."

        prompts = {
            "collect": self._build_collect_prompt,
            "ask": self._build_collect_prompt,
            "inform": self._build_inform_prompt,
            "confirm": self._build_confirm_prompt,
            "schedule": self._build_schedule_prompt,
            "finalize": self._build_finalize_prompt,
        }

        builder = prompts.get(step.step_type, self._build_default_prompt)
        return builder(step, state, rag_context)

    def _get_guide_text(self, step: StepInfo, state: ConversationState) -> str:
        """현재 상태에 맞는 Guide 텍스트 반환"""
        guides = self.select_guides(step.id, state, step.guides)
        if not guides:
            return ""
        return "\n".join(g.get("desc", "")[:500] for g in guides if g.get("desc"))

    def _get_program_text(self, step: StepInfo) -> str:
        """Program 추천 텍스트 반환"""
        if not step.programs:
            return ""
        parts = []
        for p in step.programs:
            parts.append(f"- {p.get('name', '')}: {p.get('category', '')}")
        return "추천 프로그램:\n" + "\n".join(parts)

    def _build_collect_prompt(
        self,
        step: StepInfo,
        state: ConversationState,
        rag_context: str
    ) -> str:
        # 페르소나/도메인 컨텍스트
        context = self._build_persona_context(state)

        # 미수집 항목 (힌트 포함)
        missing = []
        for ci in step.check_items:
            var_name = ci.get("variableName") or ci.get("name") or ci.get("id")
            if not var_name:
                continue
            if state.is_slot_filled(var_name):
                continue
            if self.should_skip_check_item(var_name, state):
                continue
            if var_name in AUTO_COMPUTABLE_SLOTS:
                continue
            label = ci.get("name", var_name)
            hint = CHECKITEM_HINTS.get(var_name, "")
            missing.append(f"- {label}" + (f" ({hint})" if hint else ""))

        if not missing:
            return f"{context}\n모든 정보 수집 완료. 다음 단계 안내."

        # 이미 수집된 항목
        filled = state.get_filled_slots()
        # protocolMode 등 시스템 슬롯 제외
        display_filled = {k: v for k, v in filled.items() if k not in SYSTEM_MANAGED_SLOTS}
        filled_str = ", ".join([f"{k}: {v}" for k, v in display_filled.items()]) if display_filled else "없음"

        prompt = f"""{context}
현재 단계: {step.desc or step.id}

[이미 수집된 정보]
{filled_str}

[미수집 항목]
{chr(10).join(missing)}

[지시사항]
- 미수집 항목에 대해서만 질문하세요.
- 미수집 항목이 여러 개면 한 번에 자연스럽게 모아서 질문하세요.
- 시술 방법, 효과, 부작용에 대한 설명은 하지 마세요.
- 의학적 조언이나 추천은 하지 마세요.
- 고객이 이미 제공한 정보를 다시 묻지 마세요.
- "궁금한 점이 있으신가요?", "도움이 필요하시면 연락주세요" 같은 열린 질문이나 상담 종료 멘트는 절대 하지 마세요.
- 반드시 미수집 항목을 묻는 질문으로 끝나야 합니다."""

        guide_text = self._get_guide_text(step, state)
        if guide_text:
            prompt += f"\n\n[가이드]\n{guide_text[:500]}"

        if rag_context:
            prompt += f"\n\n[참고]\n{rag_context[:500]}"
        return prompt

    def _build_inform_prompt(
        self,
        step: StepInfo,
        state: ConversationState,
        rag_context: str
    ) -> str:
        context = self._build_persona_context(state)
        filled = state.get_filled_slots()
        display_filled = {k: v for k, v in filled.items() if k not in SYSTEM_MANAGED_SLOTS}
        slots_str = ", ".join([f"{k}: {v}" for k, v in display_filled.items()]) if display_filled else "없음"

        prompt = f"""{context}
현재 단계: {step.desc or step.id} (안내)

[수집된 정보]
{slots_str}

[지시사항]
- 수집된 정보를 바탕으로 고객에게 맞춤 안내를 간결하게 제공하세요.
- 안내 내용을 전달한 뒤, 자연스럽게 다음 단계에서 필요한 추가 정보를 수집하는 질문으로 이어가세요.
- "궁금한 점이 있으신가요?" 같은 열린 질문으로 끝내지 마세요."""

        guide_text = self._get_guide_text(step, state)
        if guide_text:
            prompt += f"\n\n[가이드]\n{guide_text[:500]}"

        program_text = self._get_program_text(step)
        if program_text:
            prompt += f"\n\n{program_text}"

        if rag_context:
            prompt += f"\n\n[참고]\n{rag_context[:500]}"
        return prompt

    def _build_confirm_prompt(
        self,
        step: StepInfo,
        state: ConversationState,
        rag_context: str
    ) -> str:
        context = self._build_persona_context(state)
        filled = state.get_filled_slots()
        display_filled = {k: v for k, v in filled.items() if k not in SYSTEM_MANAGED_SLOTS}

        # 미수집 항목 확인
        missing = []
        for ci in step.check_items:
            var_name = ci.get("variableName") or ci.get("name") or ci.get("id")
            if not var_name:
                continue
            if state.is_slot_filled(var_name):
                continue
            if self.should_skip_check_item(var_name, state):
                continue
            if var_name in AUTO_COMPUTABLE_SLOTS:
                continue
            label = ci.get("name", var_name)
            hint = CHECKITEM_HINTS.get(var_name, "")
            missing.append(f"- {label}" + (f" ({hint})" if hint else ""))

        items = "\n".join([f"- {k}: {v}" for k, v in display_filled.items()])

        prompt = f"""{context}
현재 단계: {step.desc or step.id} (확인)

[수집된 상담 정보]
{items}"""

        if missing:
            prompt += f"""

[미수집 항목 - 반드시 확인 필요]
{chr(10).join(missing)}"""

        prompt += """

[지시사항]
- 수집된 정보를 자연스럽게 요약하여 고객에게 확인 요청하세요.
- 미수집 항목이 있으면 해당 항목을 먼저 질문하세요.
- 고객이 수정하고 싶은 부분이 있는지 확인하세요."""

        guide_text = self._get_guide_text(step, state)
        if guide_text:
            prompt += f"\n\n[가이드]\n{guide_text[:300]}"
        return prompt

    def _build_schedule_prompt(
        self,
        step: StepInfo,
        state: ConversationState,
        rag_context: str
    ) -> str:
        context = self._build_persona_context(state)

        prompt = f"""{context}
현재 단계: {step.desc or step.id} (일정 조율)

[지시사항]
- 고객의 희망 방문일/시술일을 확인하세요.
- 구체적인 날짜와 시간을 질문하세요."""

        guide_text = self._get_guide_text(step, state)
        if guide_text:
            prompt += f"\n\n[가이드]\n{guide_text[:300]}"
        return prompt

    def _build_finalize_prompt(
        self,
        step: StepInfo,
        state: ConversationState,
        rag_context: str
    ) -> str:
        context = self._build_persona_context(state)
        filled = state.get_filled_slots()
        display_filled = {k: v for k, v in filled.items() if k not in SYSTEM_MANAGED_SLOTS}

        # 미수집 항목 확인
        missing = []
        for ci in step.check_items:
            var_name = ci.get("variableName") or ci.get("name") or ci.get("id")
            if not var_name:
                continue
            if state.is_slot_filled(var_name):
                continue
            if self.should_skip_check_item(var_name, state):
                continue
            if var_name in AUTO_COMPUTABLE_SLOTS:
                continue
            label = ci.get("name", var_name)
            hint = CHECKITEM_HINTS.get(var_name, "")
            missing.append(f"- {label}" + (f" ({hint})" if hint else ""))

        items = "\n".join([f"- {k}: {v}" for k, v in display_filled.items()])

        prompt = f"""{context}
현재 단계: 상담 마무리 (finalize)

[수집된 전체 정보]
{items}"""

        if missing:
            prompt += f"""

[미수집 항목 - 반드시 확인 필요]
{chr(10).join(missing)}"""

        prompt += """

[지시사항]
- 미수집 항목이 있으면 해당 항목을 먼저 질문하세요.
- 모든 정보가 수집되었으면 상담 내용을 자연스럽게 요약하세요.
- 다음 단계(방문 예약, 사전 준비사항 등)를 안내하세요.
- 친절하게 마무리 인사를 하세요."""

        guide_text = self._get_guide_text(step, state)
        if guide_text:
            prompt += f"\n\n[가이드]\n{guide_text[:300]}"
        return prompt

    def _build_default_prompt(
        self,
        step: StepInfo,
        state: ConversationState,
        rag_context: str
    ) -> str:
        context = self._build_persona_context(state)

        prompt = f"""{context}
현재 단계: [{step.step_type}] {step.desc}

[지시사항]
- 현재 단계에 맞는 안내를 제공하세요.
- 시술 방법, 효과, 부작용에 대한 설명은 질문이 있을 때만 답하세요."""

        guide_text = self._get_guide_text(step, state)
        if guide_text:
            prompt += f"\n\n[가이드]\n{guide_text[:300]}"

        if rag_context:
            prompt += f"\n\n[참고]\n{rag_context[:300]}"
        return prompt

    # =========================================================================
    # Full Turn Processing
    # =========================================================================

    def process_turn(
        self,
        state: ConversationState,
        user_text: str,
        core: Any = None
    ) -> tuple[str, ConversationState]:
        """
        단일 턴 처리.

        순서:
        1. 사용자 입력 기록
        2. Persona/Scenario 해석 (첫 턴)
        3. Slot 추출 (현재 Step 기준)
        4. 다음 Step 결정 (Slot 기반 조건 평가)
        5. RAG 검색 (선택적)
        6. 응답 생성 (현재 Step 기준)
        """
        # 1. 사용자 입력 기록
        state.add_turn("user", user_text)

        # 2. Persona/Scenario 해석 (첫 턴)
        state = self.resolve_persona_scenario(state, user_text)

        # 2.5 Persona disambiguation pending → 확인 질문 반환
        if state.persona_disambiguation is not None:
            response = state.persona_disambiguation["question"]
            state.add_turn("assistant", response)
            return response, state

        if not state.current_step_id:
            response = "적절한 상담 시나리오를 찾지 못했습니다. 어떤 상담이 필요하신가요?"
            state.add_turn("assistant", response)
            return response, state

        # 3+5. Slot 추출 || RAG 검색 병렬 실행 (전략 15)
        def _do_rag_search():
            if not core:
                return ""
            try:
                chunks = core.vector_search_combined(user_text, k=2, min_score=0.5)
                context_parts = []
                total_length = 0
                max_length = 1000
                for chunk in chunks:
                    if total_length + len(chunk.content) > max_length:
                        break
                    context_parts.append(chunk.content)
                    total_length += len(chunk.content)
                return "\n".join(context_parts)
            except Exception as e:
                logger.warning(f"RAG 검색 실패: {e}")
                return ""

        with ThreadPoolExecutor(max_workers=2) as executor:
            rag_future = executor.submit(_do_rag_search)
            state = self.extract_slots(state, user_text)
            rag_context = rag_future.result()

        # 3.5. 자동 계산 가능한 Slot 산출 (전략 16)
        auto_computed = self.auto_compute_slots(state)
        if auto_computed:
            logger.info(f"자동 계산된 Slot: {auto_computed}")

        # 3.55. 상담 Persona 스코어링 (톤 레이어, Flow 무관)
        self.score_consultation_persona(state, user_text)

        # 3.6. Stale step 감지: 동일 스텝 3턴 이상이면 미수집 항목을 "미응답"으로 채움
        turns_at_step = state.increment_step_turn()
        if turns_at_step >= STALE_STEP_THRESHOLD:
            logger.warning(
                f"Stale step 감지: {state.current_step_id} ({turns_at_step}턴)"
            )
            self._handle_stale_step(state)

        # 4. 다음 Step 결정 (Slot 기반 조건 평가)
        transition = self.next_step(state)

        # protocolMode가 분기에서 설정되었으면 state에 반영
        if transition.protocol_mode:
            state.set_slot("protocolMode", transition.protocol_mode)

        if transition.next_step_id:
            state.move_to_step(transition.next_step_id)
            state.promote_prefetch_slots()  # prefetch → slots 승격

        # 4.5 연쇄 전이: inform 등 CheckItem 없는 스텝은 자동 통과
        #     건너뛴 inform 스텝의 안내 내용을 수집
        skipped_informs = self._chain_through_empty_steps(state)
        inform_context = self._build_skipped_inform_context(skipped_informs, state)

        # 6. 응답 생성 (이동 후의 현재 Step 기준)
        if state.current_step_id:
            system_prompt = self.build_step_prompt(
                state.current_step_id,
                state,
                rag_context
            )
            # 건너뛴 inform 안내 내용을 프롬프트 앞에 삽입
            if inform_context:
                system_prompt = inform_context + "\n\n" + system_prompt

            if self.openai:
                history = state.get_history_as_messages(n=6)
                response = self._generate_response(system_prompt, history)
            else:
                step = self.get_step(state.current_step_id)
                response = f"[{step.step_type}] {step.desc}" if step else "진행 중입니다."
        else:
            response = "상담이 완료되었습니다. 추가 질문이 있으시면 말씀해 주세요."

        state.add_turn("assistant", response)
        return response, state

    def _generate_response(self, system_prompt: str, history: list[dict]) -> str:
        """LLM 응답 생성"""
        messages = [{"role": "system", "content": system_prompt}]
        messages.extend(history)

        response = self.openai.chat.completions.create(
            model=self.chat_model,
            messages=messages,
            max_completion_tokens=self.max_response_tokens,
        )

        return response.choices[0].message.content

    # =========================================================================
    # 스트리밍 응답 생성 (전략 6)
    # =========================================================================

    def _generate_response_streaming(
        self,
        system_prompt: str,
        history: list[dict]
    ) -> Generator[str, None, None]:
        messages = [{"role": "system", "content": system_prompt}]
        messages.extend(history)

        stream = self.openai.chat.completions.create(
            model=self.chat_model,
            messages=messages,
            stream=True,
        )

        for chunk in stream:
            if chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content

    def process_turn_streaming(
        self,
        state: ConversationState,
        user_text: str,
        core: Any = None
    ) -> Generator[str | tuple[str, ConversationState], None, None]:
        """스트리밍으로 턴을 처리."""
        state.add_turn("user", user_text)
        state = self.resolve_persona_scenario(state, user_text)

        # Persona disambiguation pending → 확인 질문 반환
        if state.persona_disambiguation is not None:
            response = state.persona_disambiguation["question"]
            state.add_turn("assistant", response)
            yield response
            yield (response, state)
            return

        if not state.current_step_id:
            response = "적절한 상담 시나리오를 찾지 못했습니다. 어떤 상담이 필요하신가요?"
            state.add_turn("assistant", response)
            yield response
            yield (response, state)
            return

        def _do_rag_search():
            if not core:
                return ""
            try:
                chunks = core.vector_search_combined(user_text, k=2, min_score=0.5)
                context_parts = []
                total_length = 0
                max_length = 1000
                for chunk in chunks:
                    if total_length + len(chunk.content) > max_length:
                        break
                    context_parts.append(chunk.content)
                    total_length += len(chunk.content)
                return "\n".join(context_parts)
            except Exception as e:
                logger.warning(f"RAG 검색 실패: {e}")
                return ""

        with ThreadPoolExecutor(max_workers=2) as executor:
            rag_future = executor.submit(_do_rag_search)
            state = self.extract_slots(state, user_text)
            rag_context = rag_future.result()

        # 자동 계산 가능한 Slot 산출 (전략 16)
        self.auto_compute_slots(state)

        # 상담 Persona 스코어링 (톤 레이어, Flow 무관)
        self.score_consultation_persona(state, user_text)

        # Stale step 감지
        turns_at_step = state.increment_step_turn()
        if turns_at_step >= STALE_STEP_THRESHOLD:
            logger.warning(
                f"Stale step 감지: {state.current_step_id} ({turns_at_step}턴)"
            )
            self._handle_stale_step(state)

        transition = self.next_step(state)
        if transition.protocol_mode:
            state.set_slot("protocolMode", transition.protocol_mode)
        if transition.next_step_id:
            state.move_to_step(transition.next_step_id)
            state.promote_prefetch_slots()  # prefetch → slots 승격

        # 연쇄 전이: inform 등 CheckItem 없는 스텝은 자동 통과
        skipped_informs = self._chain_through_empty_steps(state)
        inform_context = self._build_skipped_inform_context(skipped_informs, state)

        if state.current_step_id and self.openai:
            system_prompt = self.build_step_prompt(
                state.current_step_id,
                state,
                rag_context
            )
            # 건너뛴 inform 안내 내용을 프롬프트 앞에 삽입
            if inform_context:
                system_prompt = inform_context + "\n\n" + system_prompt
            history = state.get_history_as_messages(n=6)

            full_response = ""
            for chunk in self._generate_response_streaming(system_prompt, history):
                full_response += chunk
                yield chunk

            response = full_response
        else:
            step = self.get_step(state.current_step_id) if state.current_step_id else None
            response = f"[{step.step_type}] {step.desc}" if step else "진행 중입니다."
            yield response

        state.add_turn("assistant", response)
        yield (response, state)

    # =========================================================================
    # 비동기 처리 (전략 4)
    # =========================================================================

    async def process_turn_async(
        self,
        state: ConversationState,
        user_text: str,
        core: Any = None
    ) -> tuple[str, ConversationState]:
        """비동기 턴 처리."""
        state.add_turn("user", user_text)
        state = self.resolve_persona_scenario(state, user_text)

        # Persona disambiguation pending → 확인 질문 반환
        if state.persona_disambiguation is not None:
            response = state.persona_disambiguation["question"]
            state.add_turn("assistant", response)
            return response, state

        if not state.current_step_id:
            response = "적절한 상담 시나리오를 찾지 못했습니다. 어떤 상담이 필요하신가요?"
            state.add_turn("assistant", response)
            return response, state

        state = await asyncio.to_thread(self.extract_slots, state, user_text)

        # 자동 계산 가능한 Slot 산출 (전략 16)
        self.auto_compute_slots(state)

        # 상담 Persona 스코어링 (톤 레이어, Flow 무관)
        self.score_consultation_persona(state, user_text)

        # Stale step 감지
        turns_at_step = state.increment_step_turn()
        if turns_at_step >= STALE_STEP_THRESHOLD:
            logger.warning(
                f"Stale step 감지: {state.current_step_id} ({turns_at_step}턴)"
            )
            self._handle_stale_step(state)

        transition = self.next_step(state)
        if transition.protocol_mode:
            state.set_slot("protocolMode", transition.protocol_mode)
        if transition.next_step_id:
            state.move_to_step(transition.next_step_id)
            state.promote_prefetch_slots()  # prefetch → slots 승격

        # 연쇄 전이: inform 등 CheckItem 없는 스텝은 자동 통과
        skipped_informs = self._chain_through_empty_steps(state)
        inform_context = self._build_skipped_inform_context(skipped_informs, state)

        rag_context = ""
        if core and hasattr(core, 'vector_search_combined_async'):
            try:
                chunks = await core.vector_search_combined_async(user_text, k=2, min_score=0.5)
                context_parts = []
                total_length = 0
                max_length = 1000
                for chunk in chunks:
                    if total_length + len(chunk.content) > max_length:
                        break
                    context_parts.append(chunk.content)
                    total_length += len(chunk.content)
                rag_context = "\n".join(context_parts)
            except Exception as e:
                logger.warning(f"RAG 검색 실패: {e}")

        if state.current_step_id:
            system_prompt = self.build_step_prompt(
                state.current_step_id,
                state,
                rag_context
            )
            # 건너뛴 inform 안내 내용을 프롬프트 앞에 삽입
            if inform_context:
                system_prompt = inform_context + "\n\n" + system_prompt
            if self.async_openai:
                history = state.get_history_as_messages(n=6)
                response = await self._generate_response_async(system_prompt, history)
            elif self.openai:
                history = state.get_history_as_messages(n=6)
                response = await asyncio.to_thread(self._generate_response, system_prompt, history)
            else:
                step = self.get_step(state.current_step_id)
                response = f"[{step.step_type}] {step.desc}" if step else "진행 중입니다."
        else:
            response = "상담이 완료되었습니다. 추가 질문이 있으시면 말씀해 주세요."

        state.add_turn("assistant", response)
        return response, state

    async def _generate_response_async(self, system_prompt: str, history: list[dict]) -> str:
        if not self.async_openai:
            return await asyncio.to_thread(self._generate_response, system_prompt, history)

        messages = [{"role": "system", "content": system_prompt}]
        messages.extend(history)

        response = await self.async_openai.chat.completions.create(
            model=self.chat_model,
            messages=messages,
        )

        return response.choices[0].message.content

