"""
flow/engine.py - FlowEngine 클래스

Mixin 기반 상속으로 모든 기능을 조합하는 최종 엔진 클래스.
"""
from __future__ import annotations
import time
from typing import Any

from neo4j import Driver
from openai import OpenAI, AsyncOpenAI

from ._types import StepInfo, TransitionResult, TurnContext
from .persona import PersonaMixin
from .navigation import NavigationMixin
from .slots import SlotMixin
from .prompt import PromptMixin
from .consultation import ConsultationMixin
from .rag_intent import RAGIntentMixin
from .turn import TurnMixin


class FlowEngine(
    PersonaMixin,
    NavigationMixin,
    SlotMixin,
    PromptMixin,
    ConsultationMixin,
    RAGIntentMixin,
    TurnMixin,
):
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
        intent_mode: str = "llm",
    ):
        self.driver = driver
        self.openai = openai_client
        self.chat_model = chat_model
        self.async_openai = async_openai_client

        self.slot_extraction_model = slot_extraction_model or chat_model
        self.max_response_tokens = max_response_tokens
        self.consultation_scoring_mode = consultation_scoring_mode  # "hybrid" | "llm" | "off"
        self.intent_mode = intent_mode  # "rule" | "llm" | "hybrid"

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
