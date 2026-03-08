"""
flow/consultation.py - ConsultationMixin

상담 Persona 스코어링 (톤/전략 레이어, Flow 무관).
"""
from __future__ import annotations
import re
import json
import logging
from typing import Any

try:
    from ..state import ConversationState
    from ..schema import (
        CONSULTATION_KEYWORDS,
        CONSULTATION_SUBJECT_PATTERNS,
        CONSULTATION_SCORE_WEIGHTS,
        CONSULTATION_SCORE_THRESHOLD,
        CONSULTATION_RECOMMENDED_Q_MAP,
    )
except ImportError:
    from state import ConversationState
    from schema import (
        CONSULTATION_KEYWORDS,
        CONSULTATION_SUBJECT_PATTERNS,
        CONSULTATION_SCORE_WEIGHTS,
        CONSULTATION_SCORE_THRESHOLD,
        CONSULTATION_RECOMMENDED_Q_MAP,
    )

logger = logging.getLogger(__name__)


class ConsultationMixin:
    """상담 Persona 스코어링 Mixin"""

    def score_consultation_persona(
        self, state: ConversationState, user_text: str
    ) -> None:
        """매 턴 상담 Persona 신호를 누적하고, threshold 초과 시 확정."""
        if self.consultation_scoring_mode == "off":
            return
        if state.consultation_persona:
            return

        if not state.consultation_scores:
            state.consultation_scores = {
                "desire": 0.0, "body": 0.0, "social": 0.0, "service": 0.0,
            }

        if self.consultation_scoring_mode == "llm":
            turn_scores = self._llm_score_consultation(user_text, state)
        else:  # hybrid
            rule_scores = self._rule_score_consultation(user_text)
            total_signal = sum(rule_scores.values())
            if total_signal >= 2.0:
                turn_scores = rule_scores
            else:
                turn_scores = self._llm_score_consultation(user_text, state)

        rq_scores = self._check_recommended_q_match(user_text)
        for persona, score in rq_scores.items():
            turn_scores[persona] = turn_scores.get(persona, 0.0) + score

        for persona in ("desire", "body", "social", "service"):
            state.consultation_scores[persona] += turn_scores.get(persona, 0.0)

        state.consultation_signals.append({
            "turn": len(state.history),
            "mode": self.consultation_scoring_mode,
            "scores": dict(turn_scores),
            "cumulative": dict(state.consultation_scores),
        })

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
                    break

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
        """추천질문 매칭."""
        scores: dict[str, float] = {}
        rq_weight = CONSULTATION_SCORE_WEIGHTS["recommended_q"]
        for question, persona in CONSULTATION_RECOMMENDED_Q_MAP.items():
            if question in user_text:
                scores[persona] = scores.get(persona, 0.0) + rq_weight
        return scores
