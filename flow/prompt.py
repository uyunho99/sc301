"""
flow/prompt.py - PromptMixin

프롬프트 빌더 (Step 타입별 시스템 프롬프트 생성).
"""
from __future__ import annotations
import logging
from typing import Any

try:
    from ..state import ConversationState
    from ..schema import (
        SYSTEM_MANAGED_SLOTS,
        CHECKITEM_HINTS,
        CONSULTATION_TONE_STRATEGIES,
    )
except ImportError:
    from state import ConversationState
    from schema import (
        SYSTEM_MANAGED_SLOTS,
        CHECKITEM_HINTS,
        CONSULTATION_TONE_STRATEGIES,
    )

from ._types import StepInfo
from ._helpers import iter_pending_checks

logger = logging.getLogger(__name__)


_PERSONA_SYSTEM_CONTEXT: dict[str, str] = {
    "slimBody":        "당신은 가슴성형(줄기세포 지방이식, 보형물 등) 전문 상담 챗봇입니다. 모든 상담은 여성 고객 대상 가슴성형 맥락에서 진행됩니다.",
    "lipoCustomer":    "당신은 가슴성형(줄기세포 지방이식, 보형물 등) 전문 상담 챗봇입니다. 모든 상담은 여성 고객 대상 가슴성형 맥락에서 진행됩니다.",
    "revisionFatigue": "당신은 가슴성형(줄기세포 지방이식, 보형물 등) 전문 상담 챗봇입니다. 모든 상담은 여성 고객 대상 가슴성형 맥락에서 진행됩니다.",
    "skinTreatment":   "당신은 미용 피부시술(필러, 보톡스, 리프팅, 레이저 등) 전문 상담 챗봇입니다. 얼굴, 목, 바디 등 다양한 부위의 비수술 피부 시술 상담을 진행합니다.",
    "longDistance":    "당신은 미용 성형외과 전문 상담 챗봇입니다. 해외·원거리 거주 고객의 다양한 성형·시술(가슴, 얼굴, 바디, 피부 등) 상담을 진행합니다.",
}
_DEFAULT_SYSTEM_CONTEXT = "당신은 미용 성형외과 전문 상담 챗봇입니다."


class PromptMixin:
    """프롬프트 빌더 Mixin"""

    def _build_persona_context(self, state: ConversationState) -> str:
        """페르소나 + 시나리오 + 상담톤 컨텍스트 문자열 생성"""
        parts = [_PERSONA_SYSTEM_CONTEXT.get(state.persona_id, _DEFAULT_SYSTEM_CONTEXT)]

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

    def _get_missing_items(self, step: StepInfo, state: ConversationState) -> list[str]:
        """미수집 CheckItem을 '- label (hint)' 형식 리스트로 반환."""
        missing = []
        for var_name, ci in iter_pending_checks(step.check_items, state, self):
            label = ci.get("name", var_name)
            hint = CHECKITEM_HINTS.get(var_name, "")
            missing.append(f"- {label}" + (f" ({hint})" if hint else ""))
        return missing

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
        context = self._build_persona_context(state)
        missing = self._get_missing_items(step, state)

        if not missing:
            return f"{context}\n모든 정보 수집 완료. 다음 단계 안내."

        filled = state.get_filled_slots()
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
- [참고] 정보가 있으면 고객의 상황에 맞게 1-2문장으로 간결히 설명한 뒤 질문하세요.
- [참고] 정보에 없는 내용은 추측하지 마세요.
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

        missing = self._get_missing_items(step, state)

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

        missing = self._get_missing_items(step, state)

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
