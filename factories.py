"""
factories.py - 인스턴스 팩토리 함수

Core, FlowEngine, StateStorage 인스턴스 생성 로직.
CLI와 외부 진입점에서 공통으로 사용.
"""
from __future__ import annotations

import os

try:
    from .core import Core, CoreConfig
    from .flow import FlowEngine
    from .state import get_storage
except ImportError:
    from core import Core, CoreConfig
    from flow import FlowEngine
    from state import get_storage


def get_core(db_mode: str = "aura") -> Core:
    """Core 인스턴스 생성

    Args:
        db_mode: "aura" (Neo4j AuraDB) 또는 "local" (로컬 Neo4j)
    """
    config = CoreConfig.from_env(db_mode=db_mode)
    return Core(config)


MODEL_PRESETS = {
    "gpt-4o":  {"chat": "gpt-4o",  "slot": "gpt-4o-mini"},
    "gpt-5":   {"chat": "gpt-5",   "slot": "gpt-5-mini"},
}


def get_flow_engine(
    core: Core,
    fast_mode: bool = False,
    model_override: str | None = None,
    consultation_scoring_mode: str = "hybrid",
    intent_mode: str = "llm",
) -> FlowEngine:
    """
    FlowEngine 인스턴스 생성 (비동기 클라이언트 포함)

    Args:
        core: Core 인스턴스
        fast_mode: True면 gpt-4o-mini로 slot 추출, 응답 토큰 제한 적용
        model_override: "gpt-4o" 또는 "gpt-5" — 지정 시 .env 설정 무시
        consultation_scoring_mode: "hybrid" | "llm" | "off"
    """
    # 모델 결정: --model 인자 > .env 값
    if model_override and model_override in MODEL_PRESETS:
        preset = MODEL_PRESETS[model_override]
        chat_model = preset["chat"]
        slot_model = preset["slot"]
    else:
        chat_model = core.config.openai_chat_model
        slot_model = os.environ.get("SLOT_EXTRACTION_MODEL")

    max_tokens_str = os.environ.get("MAX_RESPONSE_TOKENS", "500")

    # fast_mode면 gpt-4o-mini 강제 사용
    if fast_mode:
        slot_model = "gpt-4o-mini"
        max_tokens = 300  # 더 짧게
    else:
        max_tokens = int(max_tokens_str)

    return FlowEngine(
        driver=core.driver,
        openai_client=core.openai,
        chat_model=chat_model,
        async_openai_client=core.async_openai,
        slot_extraction_model=slot_model,
        max_response_tokens=max_tokens,
        consultation_scoring_mode=consultation_scoring_mode,
        intent_mode=intent_mode,
    )


def get_state_storage():
    """StateStorage 인스턴스 생성"""
    backend = os.environ.get("STATE_BACKEND", "file")
    storage_dir = os.environ.get("STATE_STORAGE_DIR", "./states")
    redis_url = os.environ.get("REDIS_URL")

    return get_storage(
        backend=backend,
        storage_dir=storage_dir,
        redis_url=redis_url
    )
