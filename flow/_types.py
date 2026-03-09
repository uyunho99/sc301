"""
flow/_types.py - 공유 데이터 타입 및 상수

FlowEngine 및 Mixin들이 공유하는 dataclass, 상수 정의.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any


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


@dataclass
class TurnContext:
    """process_turn 공통 파이프라인 결과 컨테이너"""
    state: Any  # ConversationState
    early_response: str | None = None   # 조기 반환 (disambiguation 등)
    system_prompt: str | None = None    # 최종 시스템 프롬프트
    history: list[dict] | None = None   # LLM용 대화 히스토리
    intent: str = "slot_data"           # 의도 분류 결과
    qa_context: str = ""                # 오프스크립트용 QA 컨텍스트
    source_map: dict = field(default_factory=dict)   # 인용 rank→link 매핑
    rag_mode: str = ""                               # "rag"|"no_rag"|"no_reference_fallback"
    qa_results: list = field(default_factory=list)    # QASearchResult 리스트


# 같은 스텝에 머무는 최대 턴 수. 초과 시 미수집 항목을 "미응답"으로 채워 진행.
STALE_STEP_THRESHOLD = 3
