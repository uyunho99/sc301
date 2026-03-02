"""
Default compute functions for breast surgery domain.

Each function: (state, context) -> Any | None
  - state: ConversationState
  - context: {"lookup_tables": {...}, ...}
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Any

from . import register_compute

if TYPE_CHECKING:
    from state import ConversationState

logger = logging.getLogger(__name__)


@register_compute("compute_bmi")
def compute_bmi(state: ConversationState, context: dict) -> float | None:
    """
    bodyInfo에서 키/체중 추출 → BMI 계산.
    bodyInfo 형식 예: "170cm 65kg", "키 170 몸무게 65", "170/65" 등
    """
    body_info = state.get_slot("bodyInfo")
    if body_info is None:
        return None

    body_str = str(body_info)

    height: float | None = None
    weight: float | None = None

    # 패턴 1: "170cm 65kg" 또는 "170 cm 65 kg"
    cm_match = re.search(r'(\d+(?:\.\d+)?)\s*(?:cm|센치|센티)', body_str, re.IGNORECASE)
    kg_match = re.search(r'(\d+(?:\.\d+)?)\s*(?:kg|킬로)', body_str, re.IGNORECASE)

    if cm_match:
        height = float(cm_match.group(1))
    if kg_match:
        weight = float(kg_match.group(1))

    # 패턴 2: "키 170 몸무게 65"
    if height is None:
        h_match = re.search(r'키\s*[:：]?\s*(\d+(?:\.\d+)?)', body_str)
        if h_match:
            height = float(h_match.group(1))
    if weight is None:
        w_match = re.search(r'(?:몸무게|체중)\s*[:：]?\s*(\d+(?:\.\d+)?)', body_str)
        if w_match:
            weight = float(w_match.group(1))

    # 패턴 3: "170/65" 또는 "170, 65" (순서: 키/체중)
    if height is None and weight is None:
        pair_match = re.findall(r'(\d+(?:\.\d+)?)', body_str)
        if len(pair_match) >= 2:
            nums = [float(n) for n in pair_match[:2]]
            # 키(100 이상)와 체중(100 미만) 구분
            if nums[0] >= 100 and nums[1] < 100:
                height, weight = nums[0], nums[1]
            elif nums[1] >= 100 and nums[0] < 100:
                height, weight = nums[1], nums[0]

    # bodyInfo가 숫자 하나만 있는 경우 → BMI 계산 불가
    if height is None and weight is None:
        try:
            float(body_str)
            return None
        except (ValueError, TypeError):
            pass

    if height and weight and height > 0:
        height_m = height / 100.0 if height > 3 else height  # cm→m 변환
        bmi = round(weight / (height_m ** 2), 1)
        logger.info("BMI 계산: %.1fcm / %.1fkg = %.1f", height, weight, bmi)
        return bmi

    return None


@register_compute("compute_region_bucket")
def compute_region_bucket(state: ConversationState, context: dict) -> str | None:
    """
    residenceCountry + domesticDistrict → regionBucket 자동 매핑.
    lookup_tables.region_bucket 에서 매핑 테이블을 읽어온다.
    """
    country = state.get_slot("residenceCountry")
    if country is None:
        return None

    country_str = str(country).strip()

    # 해외 거주
    if country_str.upper() == "ABROAD" or country_str in ("해외", "외국"):
        return "ABROAD"

    # 국내: domesticDistrict → S1~S6
    district = state.get_slot("domesticDistrict")
    if district is None:
        return None

    district_str = str(district).strip()

    # lookup table 로드
    region_map: dict[str, str] = context.get("lookup_tables", {}).get("region_bucket", {})

    # 정확 매칭
    if district_str in region_map:
        return region_map[district_str]

    # 부분 매칭 (예: "서울특별시" → "서울")
    for key, bucket in region_map.items():
        if key in district_str:
            return bucket

    logger.warning("regionBucket 매핑 실패: country=%s, district=%s", country_str, district_str)
    return None
