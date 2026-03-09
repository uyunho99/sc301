"""
flow/slots.py - SlotMixin

슬롯 추출, 자동 계산, 조건부 스킵 로직.
"""
from __future__ import annotations
import re
import json
import logging
from typing import Any

try:
    from ..state import ConversationState
    from ..schema import (
        AUTO_COMPUTABLE_SLOTS,
        CONDITIONAL_SKIP_RULES,
        SYSTEM_MANAGED_SLOTS,
        REGION_BUCKET_MAP,
        CHECKITEM_HINTS,
        QUERY_CHECKITEM_OPTIONS,
        BRANCHING_RULES,
    )
except ImportError:
    from state import ConversationState
    from schema import (
        AUTO_COMPUTABLE_SLOTS,
        CONDITIONAL_SKIP_RULES,
        SYSTEM_MANAGED_SLOTS,
        REGION_BUCKET_MAP,
        CHECKITEM_HINTS,
        QUERY_CHECKITEM_OPTIONS,
        BRANCHING_RULES,
    )

from ._helpers import get_check_var_name

logger = logging.getLogger(__name__)


class SlotMixin:
    """슬롯 추출, 자동 계산, 조건부 스킵 Mixin"""

    def auto_compute_slots(self, state: ConversationState) -> list[str]:
        """다른 Slot 값으로부터 자동 계산 가능한 Slot을 계산하여 state에 저장."""
        computed = []

        for slot_name, rule in AUTO_COMPUTABLE_SLOTS.items():
            if state.is_slot_filled(slot_name):
                continue

            requires = rule["requires"]
            missing = [r for r in requires if not state.is_slot_filled(r)]
            if missing:
                continue

            compute_fn = getattr(self, f'_{rule["compute"]}', None)
            if compute_fn:
                value = compute_fn(state)
                if value is not None:
                    state.set_slot(slot_name, value)
                    computed.append(slot_name)
                    logger.info(f"Auto-computed {slot_name} = {value}")

        return computed

    def _compute_bmi(self, state: ConversationState) -> float | None:
        """bodyInfo에서 키/체중 추출 → BMI 계산."""
        body_info = state.get_slot("bodyInfo")
        if body_info is None:
            return None

        body_str = str(body_info)
        height = None
        weight = None

        cm_match = re.search(r'(\d+(?:\.\d+)?)\s*(?:cm|센치|센티)', body_str, re.IGNORECASE)
        kg_match = re.search(r'(\d+(?:\.\d+)?)\s*(?:kg|킬로)', body_str, re.IGNORECASE)

        if cm_match:
            height = float(cm_match.group(1))
        if kg_match:
            weight = float(kg_match.group(1))

        if height is None:
            h_match = re.search(r'키\s*[:：]?\s*(\d+(?:\.\d+)?)', body_str)
            if h_match:
                height = float(h_match.group(1))
        if weight is None:
            w_match = re.search(r'(?:몸무게|체중)\s*[:：]?\s*(\d+(?:\.\d+)?)', body_str)
            if w_match:
                weight = float(w_match.group(1))

        if height is None and weight is None:
            pair_match = re.findall(r'(\d+(?:\.\d+)?)', body_str)
            if len(pair_match) >= 2:
                nums = [float(n) for n in pair_match[:2]]
                if nums[0] >= 100 and nums[1] < 100:
                    height, weight = nums[0], nums[1]
                elif nums[1] >= 100 and nums[0] < 100:
                    height, weight = nums[1], nums[0]

        if height is None and weight is None:
            try:
                float(body_str)
                return None
            except (ValueError, TypeError):
                pass

        if height and weight and height > 0:
            height_m = height / 100.0 if height > 3 else height
            bmi = round(weight / (height_m ** 2), 1)
            logger.info(f"BMI 계산: {height}cm / {weight}kg = {bmi}")
            return bmi

        return None

    def _compute_region_bucket(self, state: ConversationState) -> str | None:
        """residenceCountry + domesticDistrict → regionBucket 자동 매핑."""
        country = state.get_slot("residenceCountry")
        if country is None:
            return None

        country_str = str(country).strip()

        if country_str.upper() == "ABROAD" or country_str in ("해외", "외국"):
            return "ABROAD"

        district = state.get_slot("domesticDistrict")
        if district is None:
            return None

        district_str = str(district).strip()

        if district_str in REGION_BUCKET_MAP:
            return REGION_BUCKET_MAP[district_str]

        for key, bucket in REGION_BUCKET_MAP.items():
            if key in district_str:
                return bucket

        logger.warning(f"regionBucket 매핑 실패: country={country_str}, district={district_str}")
        return None

    def should_skip_check_item(
        self,
        var_name: str,
        state: ConversationState
    ) -> bool:
        """조건부 스킵: 선행 Slot 값에 따라 이 CheckItem을 건너뛸 수 있는지 확인."""
        if var_name in SYSTEM_MANAGED_SLOTS:
            return True

        if var_name in CONDITIONAL_SKIP_RULES:
            rule = CONDITIONAL_SKIP_RULES[var_name]
            when_conditions = rule["when"]

            all_met = True
            for cond_var, cond_val in when_conditions.items():
                actual = state.get_slot(cond_var)
                if actual is None:
                    all_met = False
                    break
                actual_lower = str(actual).strip().lower()
                if isinstance(cond_val, list):
                    if actual_lower not in [str(v).strip().lower() for v in cond_val]:
                        all_met = False
                        break
                else:
                    if actual_lower != str(cond_val).strip().lower():
                        all_met = False
                        break

            if all_met:
                logger.info(f"조건부 스킵: {var_name} (조건: {when_conditions})")
                return True

        return False

    def _get_checkitem_options(self, check_item_id: str) -> list[dict]:
        """CheckItem의 Option 목록 조회"""
        try:
            with self.driver.session() as session:
                result = session.run(QUERY_CHECKITEM_OPTIONS, checkItemId=check_item_id)
                return [dict(r) for r in result]
        except Exception:
            return []

    def _build_variable_desc(self, ci: dict, state: ConversationState) -> str | None:
        """CheckItem을 추출 프롬프트용 설명 문자열로 변환."""
        var_name = get_check_var_name(ci)
        if not var_name:
            return None

        if var_name in AUTO_COMPUTABLE_SLOTS:
            return None
        if var_name in SYSTEM_MANAGED_SLOTS:
            return None
        if self.should_skip_check_item(var_name, state):
            return None

        label = ci.get("name", var_name)
        dtype = ci.get("dataType", "string")

        options = self._get_checkitem_options(var_name)
        if options:
            opt_values = [o.get("value", o.get("optionId", "")) for o in options if o.get("value") or o.get("optionId")]
            return f"- {var_name}: {label} ({dtype}) [선택지: {', '.join(opt_values)}]"

        hint = CHECKITEM_HINTS.get(var_name, "")
        if hint:
            return f"- {var_name}: {label} ({dtype}) — {hint}"

        return f"- {var_name}: {label} ({dtype})"

    def extract_slots(
        self,
        state: ConversationState,
        user_text: str,
        step_id: str | None = None
    ) -> ConversationState:
        """LLM으로 사용자 발화에서 CheckItem 값 추출."""
        if not self.openai:
            logger.warning("OpenAI 클라이언트 없음, slot 추출 스킵")
            return state

        current_step = step_id or state.current_step_id
        if not current_step:
            return state

        check_items = list(self.get_step_checks(current_step))

        current_var_names = set()
        for ci in check_items:
            vn = get_check_var_name(ci)
            if vn:
                current_var_names.add(vn)

        prefetch_var_names = set()
        if current_step not in BRANCHING_RULES:
            to_steps = self._get_to_steps(current_step)
            if len(to_steps) == 1:
                next_step_id = to_steps[0]["nextStepId"]
                next_checks = self.get_step_checks(next_step_id)
                current_ids = {ci.get("id") for ci in check_items if ci.get("id")}
                for ci in next_checks:
                    ci_id = ci.get("id")
                    if ci_id and ci_id not in current_ids:
                        vn = get_check_var_name(ci) or ci_id
                        if not state.is_slot_filled(vn):
                            prefetch_var_names.add(vn)
                            check_items.append(ci)
                            current_ids.add(ci_id)

        if not check_items:
            return state

        variables = []
        valid_var_names = set()
        for ci in check_items:
            desc = self._build_variable_desc(ci, state)
            if desc:
                var_name = get_check_var_name(ci)
                variables.append(desc)
                valid_var_names.add(var_name)

        if not variables:
            return state

        prompt = f"""가슴성형 상담 정보 추출. 사용자 발화에서 해당 항목의 값을 추출하세요.

규칙:
- 사용자가 전혀 언급하지 않은 항목은 반드시 null (JSON null, 문자열 "null" 금지)
- boolean 항목은 반드시 "true" 또는 "false" 문자열로 반환
- "없습니다", "없어요", "안 했어요", "처음입니다" 등 부정/없음 답변은 "없음"으로 추출 (null 아님!)
  예: "시술 받은 적 없습니다" → pastOps: "없음", pastOpsSite: "없음"
  예: "알레르기 없어요" → allergyHistory: "없음"
- 사용자가 "해당 없습니다", "상관없어요" 등 명시적으로 해당 없음을 말한 항목만 "해당없음"으로 추출
- 중요: 사용자가 언급하지 않은 항목을 "해당없음"으로 추출하지 마세요. 반드시 null로 반환하세요.

[추출 대상]
{chr(10).join(variables)}

[발화]
{user_text}

JSON 반환: {{"변수명": "값"}}"""

        try:
            response = self.openai.chat.completions.create(
                model=self.slot_extraction_model,
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
            )

            extracted = json.loads(response.choices[0].message.content)

            for key, value in extracted.items():
                if key not in valid_var_names:
                    logger.debug(f"Slot 무시 (유효하지 않은 키): {key}")
                    continue
                if value is None:
                    continue
                if isinstance(value, str) and not value.strip():
                    continue
                if isinstance(value, str) and value.strip().lower() == "null":
                    continue
                if key in prefetch_var_names:
                    state.set_prefetch_slot(key, value)
                else:
                    state.set_slot(key, value)

            logger.debug(f"Extracted slots: {extracted}")

        except Exception as e:
            logger.error(f"Slot 추출 실패: {e}")

        return state
