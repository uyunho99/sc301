"""
flow/rag_intent.py - RAGIntentMixin

Hybrid RAG 의도 분류 + 컨텍스트 조합 + 검색 헬퍼.
"""
from __future__ import annotations
import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


class RAGIntentMixin:
    """Hybrid RAG 의도 분류 + 검색 Mixin"""

    # 한국어 질문 패턴 (의도 분류에 사용)
    _QUESTION_MARKERS = [
        "?", "까요", "나요", "건가요", "인가요", "어때요", "어떤가요",
        "얼마", "어떻게", "언제", "뭔가요", "될까요", "한가요", "할까요",
        "있나요", "없나요", "되나요", "인지", "인데", "궁금",
    ]

    _OFFSCRIPT_TEMPLATE = """[고객 질문 응대]
고객이 현재 단계와 무관한 시술 관련 질문을 했습니다.
아래 참고 정보를 바탕으로 간결하게 답변한 뒤, 현재 단계의 질문으로 자연스럽게 돌아가세요.

{qa_context}

[중요]
- 참고 정보에 없는 내용은 추측하지 마세요.
- 답변은 2-3문장으로 간결하게 하세요.
- 답변 후 반드시 현재 단계의 미수집 항목을 질문하세요."""

    _NO_PERSONA_TEMPLATE = """당신은 성형외과 상담 도우미입니다.
고객이 시술 관련 질문을 했습니다. 아래 참고 정보를 바탕으로 친절하게 답변하세요.

{qa_context}

[중요]
- 참고 정보에 없는 내용은 추측하지 마세요.
- 답변은 2-3문장으로 간결하게 하세요."""

    # =========================================================================
    # 페르소나 라우팅 (사전 분류)
    # =========================================================================

    _PERSONA_ROUTING_DESCRIPTIONS: dict[str, str] = {
        "slimBody": "마른 체형으로 지방이식 채취량이 걱정되는 고객",
        "lipoCustomer": "지방흡입과 이식을 함께 고려하거나 줄기세포 시술에 관심 있는 고객",
        "skinTreatment": "필러/보톡스/리프팅 등 비수술 피부 시술 관심 고객",
        "longDistance": "해외/타지역 거주로 방문 일정·횟수가 중요한 고객",
        "revisionFatigue": "기존 보형물 재수술/부작용 교정을 원하는 고객",
    }

    def _classify_persona_routing(self, user_text: str) -> str:
        """사용자 발화가 GraphRAG 페르소나에 매칭되는지 LLM으로 판별.

        Returns:
            "persona": 하나 이상의 페르소나 시그널 매칭 → 페르소나 매칭 진행
            "general": 페르소나 시그널 없는 순수 일반 질문 → 일반RAG
        """
        if not self.openai:
            return "persona"

        persona_lines = []
        for pid, keywords in self.PERSONA_KEYWORDS.items():
            if pid not in self._PERSONA_ROUTING_DESCRIPTIONS:
                continue
            top_kw = ", ".join(keywords[:12])
            desc = self._PERSONA_ROUTING_DESCRIPTIONS[pid]
            persona_lines.append(f"- {pid}: {desc}\n  키워드: {top_kw}")

        personas_block = "\n".join(persona_lines)

        system_prompt = f"""사용자의 발화를 분석하여, 아래 상담 페르소나 중 하나라도 해당하는지 판별하세요.

[등록된 상담 페르소나]
{personas_block}

[분류 기준]
- "persona": 발화에 위 페르소나의 키워드/상황/의도가 포함됨
- "general": 위 페르소나에 해당하지 않는 순수한 일반 정보 질문

[중요]
- 시술을 받고 싶다, 걱정이다, 고민이다 등 상담 의도가 있으면 "persona"
- 시술이 무엇인지, 비용이 얼마인지 등 단순 정보 질문이면 "general"
- 반드시 persona 또는 general 중 하나만 응답하세요."""

        try:
            response = self.openai.chat.completions.create(
                model=self.slot_extraction_model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_text},
                ],
                max_completion_tokens=20,
                temperature=0,
            )
            result = response.choices[0].message.content.strip().lower()
            if result in ("persona", "general"):
                return result
            return "persona"
        except Exception as e:
            logger.warning(f"페르소나 라우팅 분류 실패: {e}")
            return "persona"

    # =========================================================================
    # 의도 분류 (스텝 내 Hybrid RAG)
    # =========================================================================

    def _classify_user_intent(
        self,
        user_text: str,
        extracted_slot_count: int,
        qa_top_score: float,
    ) -> str:
        """사용자 발화의 의도 분류.

        Returns:
            "slot_data": CheckItem 데이터 제공
            "general_question": 일반 시술/절차 질문
            "mixed": 데이터 + 질문 혼합
        """
        if self.intent_mode == "rule":
            return self._classify_intent_rule(
                user_text, extracted_slot_count, qa_top_score
            )
        elif self.intent_mode == "llm":
            return self._classify_intent_llm(user_text)
        else:  # hybrid
            result = self._classify_intent_rule(
                user_text, extracted_slot_count, qa_top_score
            )
            if result == "uncertain":
                return self._classify_intent_llm(user_text)
            return result

    def _classify_intent_rule(
        self,
        user_text: str,
        extracted_slot_count: int,
        qa_top_score: float,
    ) -> str:
        """규칙 기반 의도 분류."""
        has_slot_data = extracted_slot_count > 0
        has_question = any(m in user_text for m in self._QUESTION_MARKERS)

        if has_slot_data and not has_question:
            return "slot_data"
        elif not has_slot_data and has_question:
            return "general_question"
        elif has_slot_data and has_question:
            return "mixed"
        else:
            if qa_top_score > 0.55:
                return "general_question"
            return "uncertain"

    def _classify_intent_llm(self, user_text: str) -> str:
        """LLM 기반 의도 분류 (gpt-4o-mini)."""
        if not self.openai:
            return "slot_data"

        system_prompt = """사용자의 발화를 분석하여 의도를 분류하세요.

분류 기준:
- slot_data: 개인 정보나 신체 정보를 제공하는 발화 (예: "키 165에 몸무게 55입니다", "서울 살아요")
- general_question: 시술/수술/회복/비용 등에 대한 일반적인 질문 (예: "회복기간이 얼마나 돼?", "부작용은 뭐가 있어?")
- mixed: 정보 제공과 질문이 함께 있는 경우 (예: "키 165인데 지방이식 가능한가요?")

반드시 slot_data, general_question, mixed 중 하나만 응답하세요."""

        try:
            response = self.openai.chat.completions.create(
                model=self.slot_extraction_model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_text},
                ],
                max_completion_tokens=20,
                temperature=0,
            )
            result = response.choices[0].message.content.strip().lower()
            if result in ("slot_data", "general_question", "mixed"):
                return result
            return "slot_data"
        except Exception as e:
            logger.warning(f"LLM 의도 분류 실패: {e}")
            return "slot_data"

    def _assemble_rag_context(
        self,
        intent: str,
        graph_rag_context: str,
        qa_context: str,
        qa_score: float,
    ) -> str:
        """의도에 따라 GraphRAG + QA 컨텍스트 조합."""
        parts = []

        if intent == "slot_data":
            if graph_rag_context:
                parts.append(graph_rag_context)
            if qa_context and qa_score > 0.45:
                parts.append(f"[일반 시술 정보]\n{qa_context[:400]}")

        elif intent == "general_question":
            if qa_context:
                parts.append(f"[관련 Q&A]\n{qa_context[:600]}")
            if graph_rag_context:
                parts.append(graph_rag_context[:300])

        elif intent == "mixed":
            if graph_rag_context:
                parts.append(graph_rag_context)
            if qa_context:
                parts.append(f"[일반 시술 정보]\n{qa_context[:400]}")

        else:
            if graph_rag_context:
                parts.append(graph_rag_context)

        return "\n\n".join(parts) if parts else ""

    # =========================================================================
    # 검색 헬퍼 (Hybrid RAG)
    # =========================================================================

    def _do_graph_rag_search(self, core: Any, user_text: str) -> tuple[str, float]:
        """GraphRAG 검색 (Surgery + Step)."""
        if not core:
            return "", 0.0
        try:
            chunks = core.vector_search_combined(user_text, k=2, min_score=0.5)
            context_parts = []
            total_length = 0
            max_length = 1000
            top_score = chunks[0].score if chunks else 0.0
            for chunk in chunks:
                if total_length + len(chunk.content) > max_length:
                    break
                context_parts.append(chunk.content)
                total_length += len(chunk.content)
            return "\n".join(context_parts), top_score
        except Exception as e:
            logger.warning(f"GraphRAG 검색 실패: {e}")
            return "", 0.0

    def _do_qa_search(self, core: Any, user_text: str) -> tuple[str, float]:
        """rag.xlsx Q&A 검색."""
        if not core or not hasattr(core, "qa_search"):
            return "", 0.0
        try:
            results = core.qa_search(user_text, k=3, min_score=0.45)
            if not results:
                return "", 0.0
            top_score = results[0].score
            context_parts = []
            total_length = 0
            max_length = 800
            for r in results:
                text = r.entry.answer
                if not text:
                    continue
                if total_length + len(text) > max_length:
                    break
                context_parts.append(text)
                total_length += len(text)
            return "\n".join(context_parts), top_score
        except Exception as e:
            logger.warning(f"QA 검색 실패: {e}")
            return "", 0.0
