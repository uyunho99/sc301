"""
flow/turn.py - TurnMixin

공통 턴 파이프라인 (_prepare_turn) + 3개 process_turn 변형.
"""
from __future__ import annotations
import logging
import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Generator

try:
    from ..state import ConversationState
except ImportError:
    from state import ConversationState

from ._types import TurnContext, STALE_STEP_THRESHOLD

logger = logging.getLogger(__name__)


class TurnMixin:
    """턴 처리 오케스트레이션 Mixin"""

    # =========================================================================
    # 공통 턴 파이프라인
    # =========================================================================

    def _prepare_turn(
        self,
        state: ConversationState,
        user_text: str,
        core: Any = None,
        *,
        search_results: tuple[tuple[str, float], tuple[str, float], int] | None = None,
    ) -> TurnContext:
        """process_turn 공통 파이프라인.

        search_results가 주어지면 (graph_rag, qa, new_slot_count) 검색 단계를 건너뜀.
        None이면 ThreadPoolExecutor로 슬롯 추출 + 검색 병렬 실행.
        """
        ctx = TurnContext(state=state)

        # 1. 사용자 입력 기록
        state.add_turn("user", user_text)

        # 1.5 페르소나 라우팅: 페르소나 매칭 대상인지 LLM으로 사전 판별
        #     아직 시나리오 진행 전이고, 일반 질문이면 페르소나 매칭 건너뜀
        if not state.is_started() and state.persona_disambiguation is None:
            routing = self._classify_persona_routing(user_text)
            if routing == "general":
                logger.info("페르소나 라우팅: general → 일반RAG")
                if search_results is not None:
                    qa_context, qa_score = search_results[1]
                else:
                    qa_context, qa_score = self._do_qa_search(core, user_text)

                if qa_context and qa_score > 0.45:
                    ctx.system_prompt = self._NO_PERSONA_TEMPLATE.format(
                        qa_context=qa_context[:800]
                    )
                    ctx.history = state.get_history_as_messages(n=6)
                    return ctx
                else:
                    ctx.early_response = (
                        "적절한 상담 시나리오를 찾지 못했습니다. "
                        "어떤 상담이 필요하신가요?"
                    )
                    state.add_turn("assistant", ctx.early_response)
                    return ctx

        # 2. Persona/Scenario 해석 (첫 턴)
        state = self.resolve_persona_scenario(state, user_text)
        ctx.state = state

        # 2.5 Persona disambiguation pending → 조기 반환
        if state.persona_disambiguation is not None:
            ctx.early_response = state.persona_disambiguation["question"]
            state.add_turn("assistant", ctx.early_response)
            return ctx

        if not state.current_step_id:
            # 페르소나 미매칭 → 일반RAG 검색 후 답변
            if search_results is not None:
                qa_context, qa_score = search_results[1]
            else:
                qa_context, qa_score = self._do_qa_search(core, user_text)

            if qa_context and qa_score > 0.45:
                ctx.system_prompt = self._NO_PERSONA_TEMPLATE.format(
                    qa_context=qa_context[:800]
                )
                ctx.history = state.get_history_as_messages(n=6)
                return ctx
            else:
                ctx.early_response = "적절한 상담 시나리오를 찾지 못했습니다. 어떤 상담이 필요하신가요?"
                state.add_turn("assistant", ctx.early_response)
                return ctx

        # 3+5. Slot 추출 + Hybrid RAG 검색
        if search_results is not None:
            (graph_rag_context, graph_rag_score), (qa_context, qa_score), new_slot_count = search_results
        else:
            with ThreadPoolExecutor(max_workers=3) as executor:
                graph_rag_future = executor.submit(self._do_graph_rag_search, core, user_text)
                qa_future = executor.submit(self._do_qa_search, core, user_text)

                prev_slot_count = len(state.get_filled_slots())
                state = self.extract_slots(state, user_text)
                new_slot_count = len(state.get_filled_slots()) - prev_slot_count

                graph_rag_context, graph_rag_score = graph_rag_future.result()
                qa_context, qa_score = qa_future.result()

        # Hybrid RAG: 의도 분류 + 컨텍스트 조합
        intent = self._classify_user_intent(user_text, new_slot_count, qa_score)
        rag_context = self._assemble_rag_context(
            intent, graph_rag_context, qa_context, qa_score
        )
        ctx.intent = intent
        ctx.qa_context = qa_context

        # 자동 계산 가능한 Slot 산출
        auto_computed = self.auto_compute_slots(state)
        if auto_computed:
            logger.info(f"자동 계산된 Slot: {auto_computed}")

        # 상담 Persona 스코어링
        self.score_consultation_persona(state, user_text)

        # Stale step 감지
        turns_at_step = state.increment_step_turn()
        if turns_at_step >= STALE_STEP_THRESHOLD:
            logger.warning(
                f"Stale step 감지: {state.current_step_id} ({turns_at_step}턴)"
            )
            self._handle_stale_step(state)

        # 다음 Step 결정
        transition = self.next_step(state)
        if transition.protocol_mode:
            state.set_slot("protocolMode", transition.protocol_mode)
        if transition.next_step_id:
            state.move_to_step(transition.next_step_id)
            state.promote_prefetch_slots()

        # 연쇄 전이
        skipped_informs = self._chain_through_empty_steps(state)
        inform_context = self._build_skipped_inform_context(skipped_informs, state)

        # 시스템 프롬프트 빌드
        if state.current_step_id:
            system_prompt = self.build_step_prompt(
                state.current_step_id, state, rag_context
            )

            # 오프스크립트 질문 삽입 (시스템 프롬프트 앞에 배치)
            if intent == "general_question" and qa_context:
                offscript = self._OFFSCRIPT_TEMPLATE.format(qa_context=qa_context[:600])
                system_prompt = offscript + "\n\n" + system_prompt

            # 건너뛴 inform 안내 삽입
            if inform_context:
                system_prompt = inform_context + "\n\n" + system_prompt

            ctx.system_prompt = system_prompt
            ctx.history = state.get_history_as_messages(n=6)

        return ctx

    # =========================================================================
    # Full Turn Processing
    # =========================================================================

    def process_turn(
        self,
        state: ConversationState,
        user_text: str,
        core: Any = None
    ) -> tuple[str, ConversationState]:
        """단일 턴 처리 (동기)."""
        ctx = self._prepare_turn(state, user_text, core)

        if ctx.early_response:
            return ctx.early_response, ctx.state

        if ctx.system_prompt and self.openai:
            response = self._generate_response(ctx.system_prompt, ctx.history)
        elif ctx.state.current_step_id:
            step = self.get_step(ctx.state.current_step_id)
            response = f"[{step.step_type}] {step.desc}" if step else "진행 중입니다."
        else:
            response = "상담이 완료되었습니다. 추가 질문이 있으시면 말씀해 주세요."

        ctx.state.add_turn("assistant", response)
        return response, ctx.state

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
        ctx = self._prepare_turn(state, user_text, core)

        if ctx.early_response:
            yield ctx.early_response
            yield (ctx.early_response, ctx.state)
            return

        if ctx.system_prompt and self.openai:
            full_response = ""
            for chunk in self._generate_response_streaming(ctx.system_prompt, ctx.history):
                full_response += chunk
                yield chunk
            response = full_response
        else:
            step = self.get_step(ctx.state.current_step_id) if ctx.state.current_step_id else None
            response = f"[{step.step_type}] {step.desc}" if step else "진행 중입니다."
            yield response

        ctx.state.add_turn("assistant", response)
        yield (response, ctx.state)

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
        prev_slot_count = len(state.get_filled_slots())
        state = await asyncio.to_thread(self.extract_slots, state, user_text)
        new_slot_count = len(state.get_filled_slots()) - prev_slot_count

        graph_rag_result: tuple[str, float] = ("", 0.0)
        qa_result: tuple[str, float] = ("", 0.0)

        if core:
            async def _graph_rag_async():
                if hasattr(core, 'vector_search_combined_async'):
                    try:
                        chunks = await core.vector_search_combined_async(
                            user_text, k=2, min_score=0.5
                        )
                        parts, length = [], 0
                        top = chunks[0].score if chunks else 0.0
                        for c in chunks:
                            if length + len(c.content) > 1000:
                                break
                            parts.append(c.content)
                            length += len(c.content)
                        return "\n".join(parts), top
                    except Exception as e:
                        logger.warning(f"GraphRAG 검색 실패: {e}")
                return "", 0.0

            async def _qa_async():
                if hasattr(core, 'qa_search'):
                    try:
                        results = await asyncio.to_thread(
                            core.qa_search, user_text, 3, 0.45
                        )
                        if not results:
                            return "", 0.0
                        top = results[0].score
                        parts, length = [], 0
                        for r in results:
                            text = r.entry.answer
                            if not text:
                                continue
                            if length + len(text) > 800:
                                break
                            parts.append(text)
                            length += len(text)
                        return "\n".join(parts), top
                    except Exception as e:
                        logger.warning(f"QA 검색 실패: {e}")
                return "", 0.0

            graph_rag_result, qa_result = await asyncio.gather(
                _graph_rag_async(), _qa_async()
            )

        ctx = self._prepare_turn(
            state, user_text, core,
            search_results=(graph_rag_result, qa_result, new_slot_count),
        )

        if ctx.early_response:
            return ctx.early_response, ctx.state

        if ctx.system_prompt:
            if self.async_openai:
                response = await self._generate_response_async(ctx.system_prompt, ctx.history)
            elif self.openai:
                response = await asyncio.to_thread(
                    self._generate_response, ctx.system_prompt, ctx.history
                )
            else:
                step = self.get_step(ctx.state.current_step_id)
                response = f"[{step.step_type}] {step.desc}" if step else "진행 중입니다."
        else:
            response = "상담이 완료되었습니다. 추가 질문이 있으시면 말씀해 주세요."

        ctx.state.add_turn("assistant", response)
        return response, ctx.state

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
