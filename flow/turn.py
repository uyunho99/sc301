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
from .rag_postprocess import (
    NO_REFERENCE_FALLBACK,
    OFFSCRIPT_FALLBACK,
    MIN_SIM_RAG,
    format_rich_context,
    build_source_map,
    make_citation_instruction,
    postprocess_response,
)

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
        search_results: tuple[tuple[str, float], tuple[str, float], int, list] | None = None,
    ) -> TurnContext:
        """process_turn 공통 파이프라인.

        search_results가 주어지면 (graph_rag, qa, new_slot_count, qa_results) 검색 단계를 건너뜀.
        None이면 ThreadPoolExecutor로 슬롯 추출 + 검색 병렬 실행.
        """
        ctx = TurnContext(state=state)
        state.add_turn("user", user_text)

        # 페르소나 라우팅 + 해석 + fallback (early exit 포함)
        if self._try_early_routing(ctx, state, user_text, core):
            return ctx

        # 검색 + 슬롯 추출 + 의도 분류
        rag_context, qa_score = self._run_search_and_classify(
            ctx, state, user_text, core, search_results
        )

        # 스텝 전이 + 연쇄 처리
        inform_context = self._advance_step(ctx, state, user_text)

        # 시스템 프롬프트 조립
        self._build_system_prompt(ctx, state, rag_context, qa_score, inform_context)

        return ctx

    # ----- 서브 함수들 -----

    def _try_early_routing(
        self,
        ctx: TurnContext,
        state: ConversationState,
        user_text: str,
        core: Any,
    ) -> bool:
        """페르소나 라우팅/해석/disambiguation/fallback 처리.

        조기 반환이 필요하면 ctx를 채우고 True 반환.
        정상 진행이면 False 반환.
        """
        # 1.5 페르소나 라우팅: 아직 시나리오 진행 전이고, 일반 질문이면 매칭 건너뜀
        if not state.is_started() and state.persona_disambiguation is None:
            routing = self._classify_persona_routing(user_text)
            if routing == "general":
                logger.info("페르소나 라우팅: general → 일반RAG")
                mode, sys_prompt, source_map = self._build_general_rag_response_context(
                    core, user_text
                )
                if mode == "no_reference_fallback":
                    ctx.early_response = NO_REFERENCE_FALLBACK
                    state.add_turn("assistant", ctx.early_response)
                    return True
                ctx.system_prompt = sys_prompt
                ctx.source_map = source_map
                ctx.rag_mode = mode
                ctx.history = state.get_history_as_messages(n=6)
                return True

        # 2. Persona/Scenario 해석 (첫 턴)
        state = self.resolve_persona_scenario(state, user_text)
        ctx.state = state

        # 2.5 Persona disambiguation pending → 조기 반환
        if state.persona_disambiguation is not None:
            ctx.early_response = state.persona_disambiguation["question"]
            state.add_turn("assistant", ctx.early_response)
            return True

        if not state.current_step_id:
            # 페르소나 미매칭 → 일반RAG (이중 임계값)
            mode, sys_prompt, source_map = self._build_general_rag_response_context(
                core, user_text
            )
            if mode == "no_reference_fallback":
                ctx.early_response = NO_REFERENCE_FALLBACK
                state.add_turn("assistant", ctx.early_response)
                return True
            ctx.system_prompt = sys_prompt
            ctx.source_map = source_map
            ctx.rag_mode = mode
            ctx.history = state.get_history_as_messages(n=6)
            return True

        return False

    def _run_search_and_classify(
        self,
        ctx: TurnContext,
        state: ConversationState,
        user_text: str,
        core: Any,
        search_results: tuple | None,
    ) -> tuple[str, float]:
        """슬롯 추출 + Hybrid RAG 검색 + 의도 분류.

        Returns (rag_context, qa_score).
        """
        if search_results is not None:
            (graph_rag_context, graph_rag_score), (qa_context, qa_score), new_slot_count, qa_results = search_results
        else:
            with ThreadPoolExecutor(max_workers=3) as executor:
                graph_rag_future = executor.submit(self._do_graph_rag_search, core, user_text)
                qa_rich_future = executor.submit(self._do_qa_search_rich, core, user_text)

                prev_slot_count = len(state.get_filled_slots())
                state = self.extract_slots(state, user_text)
                new_slot_count = len(state.get_filled_slots()) - prev_slot_count

                graph_rag_context, graph_rag_score = graph_rag_future.result()
                qa_results = qa_rich_future.result()
                qa_context, qa_score = self._collapse_qa_results(qa_results)

        intent = self._classify_user_intent(user_text, new_slot_count, qa_score)
        rag_context = self._assemble_rag_context(
            intent, graph_rag_context, qa_context, qa_score,
            qa_results=qa_results,
        )
        ctx.intent = intent
        ctx.qa_context = qa_context
        ctx.qa_results = qa_results

        return rag_context, qa_score

    def _advance_step(
        self,
        ctx: TurnContext,
        state: ConversationState,
        user_text: str,
    ) -> str:
        """자동 계산, 상담 스코어링, stale 감지, 스텝 전이, 연쇄 처리.

        Returns inform_context (건너뛴 inform 안내 문자열).
        """
        auto_computed = self.auto_compute_slots(state)
        if auto_computed:
            logger.info(f"자동 계산된 Slot: {auto_computed}")

        self.score_consultation_persona(state, user_text)

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
            state.promote_prefetch_slots()

        skipped_informs = self._chain_through_empty_steps(state)
        return self._build_skipped_inform_context(skipped_informs, state)

    def _build_system_prompt(
        self,
        ctx: TurnContext,
        state: ConversationState,
        rag_context: str,
        qa_score: float,
        inform_context: str,
    ) -> None:
        """시스템 프롬프트 빌드 + 오프스크립트/inform 삽입. ctx에 직접 기록."""
        if not state.current_step_id:
            return

        system_prompt = self.build_step_prompt(
            state.current_step_id, state, rag_context
        )

        # 오프스크립트 질문 삽입
        if ctx.intent == "general_question":
            qa_results = ctx.qa_results
            top_qa_score = qa_results[0].score if qa_results else qa_score

            if top_qa_score >= MIN_SIM_RAG and qa_results:
                rag_accepted = [r for r in qa_results if r.score >= MIN_SIM_RAG]
                rich_context = format_rich_context(rag_accepted)
                source_map = build_source_map(rag_accepted)
                citation_inst = make_citation_instruction(source_map) if source_map else ""
                offscript = self._OFFSCRIPT_TEMPLATE_RICH.format(
                    qa_context=rich_context
                )
                if citation_inst:
                    offscript += "\n" + citation_inst
                ctx.source_map = source_map
                system_prompt = offscript + "\n\n" + system_prompt
            else:
                system_prompt = OFFSCRIPT_FALLBACK + "\n\n" + system_prompt

        if inform_context:
            system_prompt = inform_context + "\n\n" + system_prompt

        ctx.system_prompt = system_prompt
        ctx.history = state.get_history_as_messages(n=6)

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
            response = self._generate_response(
                ctx.system_prompt, ctx.history,
                unlimited=(ctx.rag_mode == "rag"),
            )
        elif ctx.state.current_step_id:
            step = self.get_step(ctx.state.current_step_id)
            response = f"[{step.step_type}] {step.desc}" if step else "진행 중입니다."
        else:
            response = "상담이 완료되었습니다. 추가 질문이 있으시면 말씀해 주세요."

        # 인용 후처리
        if ctx.source_map:
            response = postprocess_response(response, ctx.source_map)

        ctx.state.add_turn("assistant", response)
        return response, ctx.state

    def _generate_response(
        self, system_prompt: str, history: list[dict],
        *, unlimited: bool = False,
    ) -> str:
        """LLM 응답 생성. unlimited=True면 max_completion_tokens 제한 없음."""
        messages = [{"role": "system", "content": system_prompt}]
        messages.extend(history)

        kwargs: dict = {
            "model": self.chat_model,
            "messages": messages,
        }
        if not unlimited:
            kwargs["max_completion_tokens"] = self.max_response_tokens

        response = self.openai.chat.completions.create(**kwargs)
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

        # 인용 후처리
        if ctx.source_map:
            response = postprocess_response(response, ctx.source_map)

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
        qa_results_list: list = []

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
                            core.qa_search, user_text, 5, 0.35
                        )
                        if not results:
                            return "", 0.0, []
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
                        return "\n".join(parts), top, results
                    except Exception as e:
                        logger.warning(f"QA 검색 실패: {e}")
                return "", 0.0, []

            graph_rag_result, qa_full_result = await asyncio.gather(
                _graph_rag_async(), _qa_async()
            )
            qa_text, qa_score_val, qa_results_list = qa_full_result
            qa_result = (qa_text, qa_score_val)

        ctx = self._prepare_turn(
            state, user_text, core,
            search_results=(graph_rag_result, qa_result, new_slot_count, qa_results_list),
        )

        if ctx.early_response:
            return ctx.early_response, ctx.state

        if ctx.system_prompt:
            unlimited = (ctx.rag_mode == "rag")
            if self.async_openai:
                response = await self._generate_response_async(
                    ctx.system_prompt, ctx.history, unlimited=unlimited,
                )
            elif self.openai:
                response = await asyncio.to_thread(
                    self._generate_response, ctx.system_prompt, ctx.history,
                    unlimited=unlimited,
                )
            else:
                step = self.get_step(ctx.state.current_step_id)
                response = f"[{step.step_type}] {step.desc}" if step else "진행 중입니다."
        else:
            response = "상담이 완료되었습니다. 추가 질문이 있으시면 말씀해 주세요."

        # 인용 후처리
        if ctx.source_map:
            response = postprocess_response(response, ctx.source_map)

        ctx.state.add_turn("assistant", response)
        return response, ctx.state

    async def _generate_response_async(
        self, system_prompt: str, history: list[dict],
        *, unlimited: bool = False,
    ) -> str:
        if not self.async_openai:
            return await asyncio.to_thread(
                self._generate_response, system_prompt, history,
                unlimited=unlimited,
            )

        messages = [{"role": "system", "content": system_prompt}]
        messages.extend(history)

        response = await self.async_openai.chat.completions.create(
            model=self.chat_model,
            messages=messages,
        )

        return response.choices[0].message.content
