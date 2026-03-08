"""
flow/persona.py - PersonaMixin

Persona/Scenario 해석, disambiguation, 키워드 매칭.
"""
from __future__ import annotations
import logging
from typing import Any

try:
    from ..state import ConversationState
    from ..schema import (
        QUERY_ALL_PERSONAS,
        QUERY_PERSONA_BY_ID,
        QUERY_SCENARIO_BY_ID,
        QUERY_SCENARIO_START_STEP,
    )
except ImportError:
    from state import ConversationState
    from schema import (
        QUERY_ALL_PERSONAS,
        QUERY_PERSONA_BY_ID,
        QUERY_SCENARIO_BY_ID,
        QUERY_SCENARIO_START_STEP,
    )

logger = logging.getLogger(__name__)


class PersonaMixin:
    """Persona/Scenario 해석 Mixin"""

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
        """첫 턴에서 사용자 발화 기반으로 Persona/Scenario 추론 및 할당."""
        if state.is_started():
            return state

        # Turn 2: disambiguation 해소
        if state.persona_disambiguation is not None:
            combined = (
                state.persona_disambiguation["original_text"] + " " + user_text
            )
            personas = self.get_all_personas()
            if personas:
                state.persona_id = self._infer_persona(combined, personas)
            state.persona_disambiguation = None

        # Turn 1: 첫 페르소나 판별
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
                    return state

                state.persona_id = (
                    scores[0]["id"] if scores and scores[0]["score"] > 0
                    else personas[0]["personaId"]
                )
            else:
                state.persona_id = personas[0]["personaId"]

        # Scenario & Step 할당
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
    PERSONA_AMBIGUITY_THRESHOLD = 1

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

    PERSONA_KEYWORDS: dict[str, list[str]] = {
        "slimBody": [
            "슬림", "마른", "체형", "체지방", "다이어트", "복부", "팔뚝", "허벅지", "바디", "체중",
            "지방이식", "지방주입", "fat grafting", "fat transfer", "채취", "채취량",
            "생착", "생착률", "도너부위", "채취 부위", "뺄 데", "지방이 없어서",
            "체지방 부족", "체지방률", "저체중", "근육량", "벌크업",
            "살찌우기", "증량", "벌크", "체중 늘리기",
            "운동선수", "바디프로필", "피트니스", "보디빌딩",
            "출산", "산후", "모유수유", "산후 다이어트",
            "트랜스젠더", "트랜스", "호르몬", "hrt",
            "제 몸에도 가능", "대안", "가능 여부",
        ],
        "lipoCustomer": [
            "지방흡입", "지방이식", "리포", "흡입",
            "람스", "바디라인", "라인 정리", "fat transfer", "빼고 채우는",
            "효과 언제", "안정화", "붓기 빠지면",
            "울퉁불퉁", "비대칭", "재수술 위험",
            "가성비", "비용 대비", "가격 차이", "추가 비용",
            "줄기세포", "svf", "prp", "농축", "일반 지방이식", "장단점", "효과 차이",
            "바로 상담", "빨리 진행", "이번 주", "다음 주",
        ],
        "skinTreatment": [
            "피부", "레이저", "보톡스", "필러", "리프팅", "피부과", "여드름", "주름", "안티에이징",
            "팔자주름", "팔자", "볼 꺼짐", "볼살", "중안부",
            "나이 들어 보임", "동안", "어려 보이고 싶",
            "필러 해봤", "보톡스 해봤", "효과가 금방 빠졌",
            "오래 유지", "지속", "한 번에", "리터치", "재시술", "다시 꺼짐",
            "안전", "회복기간", "붓기", "멍", "통증", "일상생활",
            "쉽게 설명", "직관적", "차이가 뭐예요",
        ],
        "longDistance": [
            "원거리", "타지역", "해외", "지방거주", "교통", "유학",
            "캐나다", "토론토", "미국", "일본", "중국", "호주", "영국",
            "출국", "입국", "비행기", "항공", "시차", "해외번호",
            "방문 기간", "체류 기간", "당일", "하루 만에", "원데이",
            "내원 횟수", "몇 번", "방문 횟수", "빠른 일정",
            "비행기 타도 되나요", "장거리 이동", "출국 전",
            "부산", "대구", "대전", "광주", "제주", "강원",
        ],
        "revisionFatigue": [
            "재수술", "부작용", "재교정", "불만족", "수정", "보형물",
            "리비전", "이전 수술", "기존 보형물", "몇 년 전 수술",
            "제거", "완전 제거", "빼고", "교체", "보형물 종류 변경",
            "석회화", "괴사", "구형구축", "파열", "염증", "피막", "캡슐렉토미",
            "비대칭", "처짐", "모양 교정", "사이즈 줄이기", "사이즈 키우기",
            "이물감", "딱딱", "촉감", "심리적 거부",
            "흉터", "비노출", "절개 위치",
            "원스텝", "한번에 끝", "최소 횟수",
        ],
        "P1_BreastConsult": ["가슴", "유방", "브레스트", "가슴성형", "가슴확대", "가슴축소"],
        "P2_FaceConsult": ["코", "눈", "얼굴", "안면", "윤곽", "턱", "이마", "쌍꺼풀", "코성형"],
    }

    PERSONA_SIGNAL_RULES: dict[str, list[dict]] = {
        "slimBody": [
            {"signals": ["지방이식", "마른"], "bonus": 3},
            {"signals": ["지방이식", "채취"], "bonus": 3},
            {"signals": ["체지방", "부족"], "bonus": 3},
            {"signals": ["체지방", "낮"], "bonus": 2},
            {"signals": ["증량", "지방이식"], "bonus": 2},
        ],
        "lipoCustomer": [
            {"signals": ["흡입", "이식"], "bonus": 3},
            {"signals": ["줄기세포", "지방이식"], "bonus": 3},
            {"signals": ["비용 대비", "효과"], "bonus": 2},
        ],
        "skinTreatment": [
            {"signals": ["팔자", "볼"], "bonus": 3},
            {"signals": ["자연스럽", "유지"], "bonus": 2},
            {"signals": ["필러", "보톡스"], "bonus": 2},
            {"signals": ["안전", "회복"], "bonus": 2},
        ],
        "longDistance": [
            {"signals": ["해외", "일정"], "bonus": 3},
            {"signals": ["유학", "한국"], "bonus": 3},
            {"signals": ["체류", "기간"], "bonus": 3},
            {"signals": ["출국", "비행기"], "bonus": 3},
            {"signals": ["내원", "횟수"], "bonus": 2},
        ],
        "revisionFatigue": [
            {"signals": ["재수술", "이물감"], "bonus": 4},
            {"signals": ["재수술", "가슴"], "bonus": 4},
            {"signals": ["보형물", "제거"], "bonus": 4},
            {"signals": ["보형물", "구형구축"], "bonus": 4},
            {"signals": ["이전 수술", "가슴"], "bonus": 4},
            {"signals": ["석회화", "괴사"], "bonus": 3},
            {"signals": ["보형물", "딱딱"], "bonus": 3},
            {"signals": ["보형물", "빼고"], "bonus": 3},
        ],
    }

    _P5_REQUIRED_SIGNALS = [
        "재수술", "재교정", "리비전", "이전 수술", "기존 보형물",
        "몇 년 전 수술", "보형물", "제거", "교체", "구형구축",
        "이물감", "석회화", "괴사", "피막",
    ]

    def _score_personas(self, user_text: str, personas: list[dict]) -> list[dict]:
        """전체 Persona 점수 산출."""
        text_lower = user_text.lower()
        valid_ids = {p["personaId"] for p in personas}
        results = []

        for persona_id, keywords in self.PERSONA_KEYWORDS.items():
            if persona_id not in valid_ids:
                continue
            score = sum(1 for kw in keywords if kw in text_lower)

            if persona_id in self.PERSONA_SIGNAL_RULES:
                for rule in self.PERSONA_SIGNAL_RULES[persona_id]:
                    if all(sig in text_lower for sig in rule["signals"]):
                        score += rule["bonus"]

            if persona_id == "revisionFatigue":
                if not any(s in text_lower for s in self._P5_REQUIRED_SIGNALS):
                    score = max(0, score - 5)

            results.append({"id": persona_id, "score": score})

        results.sort(key=lambda x: x["score"], reverse=True)
        return results

    def _infer_persona(self, user_text: str, personas: list[dict]) -> str:
        """키워드 + 복합 신호 매칭으로 Persona 추론"""
        scores = self._score_personas(user_text, personas)
        if scores and scores[0]["score"] > 0:
            return scores[0]["id"]
        return personas[0]["personaId"]
