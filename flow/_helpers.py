"""
flow/_helpers.py - Check-item 필터링 유틸리티

CheckItem dict에서 변수명 추출, 미수집 항목 필터링 등
여러 Mixin에서 공유하는 순수 함수 모음.
"""
from __future__ import annotations

from typing import Iterator, TYPE_CHECKING

if TYPE_CHECKING:
    pass  # ConversationState 등은 런타임에 필요하지 않음

try:
    from ..schema import AUTO_COMPUTABLE_SLOTS
except ImportError:
    from schema import AUTO_COMPUTABLE_SLOTS


def get_check_var_name(ci: dict) -> str | None:
    """CheckItem dict에서 변수명을 추출한다."""
    return ci.get("variableName") or ci.get("name") or ci.get("id")


def iter_pending_checks(
    check_items: list[dict],
    state,
    engine,
    *,
    include_auto: bool = False,
) -> Iterator[tuple[str, dict]]:
    """미수집 CheckItem만 (var_name, ci) 튜플로 yield.

    필터링 순서:
      1. 변수명 없으면 스킵
      2. 이미 채워진 슬롯이면 스킵
      3. should_skip_check_item이면 스킵 (SYSTEM_MANAGED 포함)
      4. AUTO_COMPUTABLE이면 스킵 (include_auto=True 시 통과)
    """
    for ci in check_items:
        var_name = get_check_var_name(ci)
        if not var_name:
            continue
        if state.is_slot_filled(var_name):
            continue
        if engine.should_skip_check_item(var_name, state):
            continue
        if not include_auto and var_name in AUTO_COMPUTABLE_SLOTS:
            continue
        yield var_name, ci
