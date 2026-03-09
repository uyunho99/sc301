"""
flow/navigation.py - NavigationMixin

Step 전이, 분기 평가, Guide 선택 로직.
"""
from __future__ import annotations
import logging
from typing import Any

try:
    from ..state import ConversationState
    from ..schema import (
        QUERY_STEP_BY_ID,
        QUERY_STEP_CHECKS,
        QUERY_NEXT_STEPS_BY_TO,
        QUERY_NEXT_STEP_BY_LEADS_TO,
        QUERY_DECISION_RULE_CONDITIONS,
        QUERY_RULE_CONDITIONS_VIA_CONSIDERS,
        QUERY_HAS_CONSIDERS,
        QUERY_SCENARIO_ALL_CHECKS,
        BRANCHING_RULES,
        RULE_CONDITION_MAP,
        OR_LOGIC_RULES,
        GUIDE_SELECTION_RULES,
        AUTO_COMPUTABLE_SLOTS,
        CHECKITEM_HINTS,
    )
except ImportError:
    from state import ConversationState
    from schema import (
        QUERY_STEP_BY_ID,
        QUERY_STEP_CHECKS,
        QUERY_NEXT_STEPS_BY_TO,
        QUERY_NEXT_STEP_BY_LEADS_TO,
        QUERY_DECISION_RULE_CONDITIONS,
        QUERY_RULE_CONDITIONS_VIA_CONSIDERS,
        QUERY_HAS_CONSIDERS,
        QUERY_SCENARIO_ALL_CHECKS,
        BRANCHING_RULES,
        RULE_CONDITION_MAP,
        OR_LOGIC_RULES,
        GUIDE_SELECTION_RULES,
        AUTO_COMPUTABLE_SLOTS,
        CHECKITEM_HINTS,
    )

from ._types import StepInfo, TransitionResult, STALE_STEP_THRESHOLD
from ._helpers import get_check_var_name, iter_pending_checks

logger = logging.getLogger(__name__)


class NavigationMixin:
    """Step 전이, 분기 평가, Guide 선택 Mixin"""

    # =========================================================================
    # Step Navigation (전략 1: 캐싱 적용)
    # =========================================================================

    def get_step(self, step_id: str) -> StepInfo | None:
        """Step 정보 조회 (캐싱) - Guide, Program, ReferenceSlot 포함"""
        cache_key = f"step_{step_id}"
        if step_id in self._step_cache and self._is_cache_valid(cache_key):
            return self._step_cache[step_id]

        with self.driver.session() as session:
            result = session.run(QUERY_STEP_BY_ID, stepId=step_id)
            record = result.single()
            if not record:
                return None

            check_items = [ci for ci in (record["checkItems"] or []) if ci.get("id")]
            guides = [g for g in (record["guides"] or []) if g.get("id")]
            programs = [p for p in (record["programs"] or []) if p.get("id")]
            ref_slots = [r for r in (record["referenceSlots"] or []) if r]

            step_type = record.get("stepType") or ""
            if not step_type:
                step_type = self._infer_step_type(step_id)

            step_info = StepInfo(
                id=record["stepId"],
                desc=record["desc"] or "",
                step_type=step_type,
                check_items=check_items,
                guides=guides,
                programs=programs,
                reference_slots=ref_slots,
            )
            self._set_cache_timestamp(cache_key)
            self._step_cache[step_id] = step_info
            return step_info

    def _infer_step_type(self, step_id: str) -> str:
        """Step ID에서 타입 추론 (DB에 stepType이 null인 경우)"""
        step_id_lower = step_id.lower()
        if "collect" in step_id_lower or "precollect" in step_id_lower:
            return "collect"
        elif "asklifestyle" in step_id_lower or "askdetail" in step_id_lower or "asksurgery" in step_id_lower or "askmedical" in step_id_lower:
            return "ask"
        elif "informsurg" in step_id_lower or "informinfo" in step_id_lower:
            return "inform"
        elif "confirm" in step_id_lower:
            return "confirm"
        elif "finalize" in step_id_lower:
            return "finalize"
        return "collect"

    def _is_auto_transition_step(self, step_id: str) -> bool:
        """사용자 입력 없이 자동 전이해야 하는 스텝인지 확인 (inform 등)"""
        step = self.get_step(step_id)
        if not step:
            return False
        return step.step_type in ("inform",)

    def get_step_checks(self, step_id: str) -> list[dict]:
        """Step의 CheckItem 목록 조회 (캐싱)"""
        cache_key = f"step_checks_{step_id}"
        if step_id in self._step_checks_cache and self._is_cache_valid(cache_key):
            return self._step_checks_cache[step_id]

        with self.driver.session() as session:
            result = session.run(QUERY_STEP_CHECKS, stepId=step_id)
            checks = [dict(r) for r in result]
            self._set_cache_timestamp(cache_key)
            self._step_checks_cache[step_id] = checks
            return checks

    def get_scenario_all_checks(self, scenario_id: str) -> list[dict]:
        """시나리오 전체 CheckItem 목록 조회 (ASKS_FOR 관계, 캐싱)"""
        cache_key = f"scenario_checks_{scenario_id}"
        if scenario_id in self._step_checks_cache and self._is_cache_valid(cache_key):
            return self._step_checks_cache[scenario_id]

        with self.driver.session() as session:
            result = session.run(QUERY_SCENARIO_ALL_CHECKS, scenarioId=scenario_id)
            checks = [dict(r) for r in result]
            self._set_cache_timestamp(cache_key)
            self._step_checks_cache[scenario_id] = checks
            return checks

    # =========================================================================
    # Step Transition (TO + BRANCHING_RULES 기반)
    # =========================================================================

    def next_step(self, state: ConversationState) -> TransitionResult:
        """다음 Step 결정."""
        if not state.current_step_id:
            return TransitionResult(None, "end", {"reason": "current_step_id 없음"})

        step_id = state.current_step_id

        if not self._is_auto_transition_step(step_id) and not self._are_step_checks_filled(step_id, state):
            return TransitionResult(
                None, "stay",
                {"reason": "필수 CheckItem 미수집", "stepId": step_id}
            )

        if step_id in BRANCHING_RULES:
            result = self._evaluate_branching_rules(step_id, state)
            if result:
                return result
            logger.warning(
                f"분기 규칙 매칭 실패, TO 관계로 fallback: step={step_id}"
            )

        to_steps = self._get_to_steps(step_id)
        if to_steps:
            if len(to_steps) == 1:
                return TransitionResult(
                    to_steps[0]["nextStepId"],
                    "to",
                    {"singlePath": True}
                )
            else:
                return TransitionResult(
                    to_steps[0]["nextStepId"],
                    "to",
                    {"multiPath": True, "candidates": [s["nextStepId"] for s in to_steps]}
                )

        leads_to = self._get_leads_to(step_id)
        if leads_to:
            return TransitionResult(leads_to, "leadsTo", {"fallback": True})

        return TransitionResult(None, "end", {"reason": "더 이상 전이 없음"})

    def _chain_through_empty_steps(self, state: ConversationState) -> list[str]:
        """연쇄 전이: 현재 스텝에 미수집 CheckItem이 없으면 자동으로 다음 스텝까지 진행."""
        skipped_inform_steps = []

        for _ in range(5):
            if not state.current_step_id:
                break

            self.auto_compute_slots(state)

            is_auto = self._is_auto_transition_step(state.current_step_id)

            if not is_auto and not self._are_step_checks_filled(state.current_step_id, state):
                break

            if is_auto:
                skipped_inform_steps.append(state.current_step_id)

            chain = self.next_step(state)
            if chain.protocol_mode:
                state.set_slot("protocolMode", chain.protocol_mode)
            if chain.next_step_id:
                logger.info(f"연쇄 전이: {state.current_step_id} → {chain.next_step_id}")
                state.move_to_step(chain.next_step_id)
            else:
                break

        return skipped_inform_steps

    def _build_skipped_inform_context(
        self,
        skipped_steps: list[str],
        state: ConversationState
    ) -> str:
        """건너뛴 inform 스텝의 Guide/Program 안내 내용을 모아 프롬프트에 포함."""
        if not skipped_steps:
            return ""

        parts = []
        for step_id in skipped_steps:
            step = self.get_step(step_id)
            if not step:
                continue
            guide_text = self._get_guide_text(step, state)
            program_text = self._get_program_text(step)
            section = f"### {step.desc or step_id}"
            if guide_text:
                section += f"\n{guide_text[:500]}"
            if program_text:
                section += f"\n{program_text}"
            if step.desc and not guide_text and not program_text:
                section += f"\n(안내 단계: {step.desc})"
            parts.append(section)

        if not parts:
            return ""

        return (
            "[아래 안내 내용을 반드시 고객에게 간략히 설명한 후, "
            "다음 질문으로 자연스럽게 이어가세요]\n\n"
            + "\n\n".join(parts)
        )

    def _handle_stale_step(self, state: ConversationState) -> None:
        """동일 스텝에 STALE_STEP_THRESHOLD 턴 이상 머물렀을 때 미수집 항목을 '미응답'으로 채움."""
        step_id = state.current_step_id
        if not step_id:
            return

        step = self.get_step(step_id)
        if not step:
            return

        if step.step_type in ("confirm", "finalize"):
            return

        checks = self.get_step_checks(step_id)
        for vn, ci in iter_pending_checks(checks or [], state, self):
            state.set_slot(vn, "미응답")
            logger.info(f"Stale step 복구: {vn} = '미응답' (step={step_id})")

    def _are_step_checks_filled(self, step_id: str, state: ConversationState) -> bool:
        """현재 Step의 CHECKS CheckItem이 모두 수집되었는지 확인."""
        checks = self.get_step_checks(step_id)
        if not checks:
            return True

        for ci in checks:
            var_name = get_check_var_name(ci)
            if not var_name:
                continue
            if state.is_slot_filled(var_name):
                continue
            if self.should_skip_check_item(var_name, state):
                continue
            if var_name in AUTO_COMPUTABLE_SLOTS:
                self.auto_compute_slots(state)
                if state.is_slot_filled(var_name):
                    continue
            return False
        return True

    def _get_to_steps(self, step_id: str) -> list[dict]:
        """TO 관계로 연결된 다음 Step 목록 조회"""
        with self.driver.session() as session:
            result = session.run(QUERY_NEXT_STEPS_BY_TO, stepId=step_id)
            return [dict(r) for r in result]

    def _get_leads_to(self, step_id: str) -> str | None:
        """leadsTo 관계로 연결된 다음 Step 조회 (레거시 호환)"""
        with self.driver.session() as session:
            result = session.run(QUERY_NEXT_STEP_BY_LEADS_TO, stepId=step_id)
            record = result.single()
            return record["nextStepId"] if record else None

    def _evaluate_branching_rules(
        self,
        step_id: str,
        state: ConversationState
    ) -> TransitionResult | None:
        """BRANCHING_RULES 기반 분기 조건 평가"""
        rules = BRANCHING_RULES[step_id]
        sorted_rules = sorted(rules, key=lambda r: r.get("priority", 0), reverse=True)

        default_rule = None

        for rule in sorted_rules:
            if rule.get("isDefault"):
                default_rule = rule
                continue

            if rule.get("ruleId"):
                if self._evaluate_rule_filtered(rule["ruleId"], state):
                    protocol = self._determine_protocol_mode(rule, state)
                    return TransitionResult(
                        rule["targetStepId"],
                        "branching",
                        {"transitionId": rule["transitionId"], "ruleId": rule["ruleId"]},
                        protocol_mode=protocol,
                    )
            elif rule.get("conditionVar"):
                actual = state.get_slot(rule["conditionVar"])
                if actual is not None:
                    if self._compare_values(
                        str(actual),
                        rule.get("conditionOp", "="),
                        rule.get("conditionRef", "")
                    ):
                        return TransitionResult(
                            rule["targetStepId"],
                            "branching",
                            {"transitionId": rule["transitionId"], "directCondition": True},
                        )

        if default_rule:
            return TransitionResult(
                default_rule["targetStepId"],
                "branching",
                {"transitionId": default_rule["transitionId"], "isDefault": True},
            )

        return None

    def _determine_protocol_mode(self, rule: dict, state: ConversationState) -> str | None:
        """분기 규칙에 따른 protocolMode 결정"""
        rule_id = rule.get("ruleId", "")

        if rule_id == "ruleBodyFatHigh":
            return "STANDARD"
        elif rule_id == "ruleBodyFatLow":
            return "LOW-FAT"
        elif rule_id == "ruleRegionRemote":
            return "FULL"
        elif rule_id == "ruleRegionSemiRemote":
            return "SEMI-REMOTE"
        elif rule_id == "ruleCancerNone":
            return "STANDARD"
        elif rule_id == "ruleCancerConditional":
            return "CONDITIONAL"
        elif rule_id == "ruleCancerNotAllowed":
            return "NOT_ALLOWED"

        return None

    def _check_has_considers(self) -> bool:
        """DB에 CONSIDERS 관계가 존재하는지 확인 (1회 실행 후 캐싱)."""
        if self._has_considers is not None:
            return self._has_considers
        try:
            with self.driver.session() as session:
                result = session.run(QUERY_HAS_CONSIDERS)
                record = result.single()
                self._has_considers = bool(record and record["hasConsiders"])
        except Exception:
            self._has_considers = False
        logger.info("DB CONSIDERS support: %s", self._has_considers)
        return self._has_considers

    def _load_conditions_via_considers(self, rule_id: str) -> list[dict] | None:
        """CONSIDERS 관계로 DecisionRule의 Condition 로드."""
        if rule_id in self._rule_conditions_cache:
            return self._rule_conditions_cache[rule_id]

        with self.driver.session() as session:
            result = session.run(
                QUERY_RULE_CONDITIONS_VIA_CONSIDERS,
                ruleId=rule_id,
            )
            record = result.single()
            if not record:
                return None

            conditions = record.get("conditions", [])
            conditions = [c for c in conditions if c.get("condId")]
            if not conditions:
                return None

            self._rule_conditions_cache[rule_id] = conditions

            for c in conditions:
                cid = c.get("condId")
                if cid and cid not in self._condition_cache:
                    self._condition_cache[cid] = c

            return conditions

    def _evaluate_rule_filtered(self, rule_id: str, state: ConversationState) -> bool:
        """DecisionRule 평가 (3-tier fallback)."""
        conditions = None

        if self._check_has_considers():
            conditions = self._load_conditions_via_considers(rule_id)

        if conditions is None:
            relevant_cond_ids = RULE_CONDITION_MAP.get(rule_id)
            if relevant_cond_ids:
                conditions = self._load_conditions(relevant_cond_ids)

        if conditions is None:
            return self._evaluate_rule_from_db(rule_id, state)

        if not conditions:
            return True

        results = [self._evaluate_condition(c, state) for c in conditions]

        if rule_id in OR_LOGIC_RULES:
            return any(results)
        return all(results)

    def _load_conditions(self, condition_ids: list[str]) -> list[dict]:
        """Condition 노드 로드 (캐싱)"""
        conditions = []
        missing_ids = []

        for cid in condition_ids:
            if cid in self._condition_cache:
                conditions.append(self._condition_cache[cid])
            else:
                missing_ids.append(cid)

        if missing_ids:
            with self.driver.session() as session:
                for cid in missing_ids:
                    result = session.run(
                        "MATCH (c:Condition {id: $condId}) "
                        "RETURN c.id AS condId, c.input AS input, c.op AS op, "
                        "c.ref AS ref, c.refType AS refType, c.missingPolicy AS missingPolicy",
                        condId=cid
                    )
                    record = result.single()
                    if record:
                        cond = dict(record)
                        self._condition_cache[cid] = cond
                        conditions.append(cond)

        return conditions

    def _evaluate_rule_from_db(self, rule_id: str, state: ConversationState) -> bool:
        """DB에서 DecisionRule 조건 로드 후 평가 (fallback)"""
        with self.driver.session() as session:
            result = session.run(QUERY_DECISION_RULE_CONDITIONS, ruleId=rule_id)
            record = result.single()

            if not record:
                return True

            logic = record.get("logic", "AND")
            conditions = record.get("conditions", [])

            if not conditions:
                return True

            results = [self._evaluate_condition(c, state) for c in conditions]

            if logic == "OR":
                return any(results)
            else:
                return all(results)

    def _evaluate_condition(self, condition: dict, state: ConversationState) -> bool:
        """단일 Condition 평가 (input/op/ref/refType 기반)"""
        input_var = condition.get("input")
        op = condition.get("op")
        ref = condition.get("ref")
        ref_type = condition.get("refType", "string")
        missing_policy = condition.get("missingPolicy", "UNKNOWN")

        actual_value = state.get_slot(input_var)

        if actual_value is None:
            if missing_policy == "TRUE":
                return True
            elif missing_policy == "FALSE":
                return False
            else:
                return False

        return self._compare_values(str(actual_value), op, ref, ref_type)

    def _compare_values(
        self,
        actual: str,
        op: str,
        ref: str,
        ref_type: str = "string"
    ) -> bool:
        """값 비교 연산"""
        actual = str(actual) if actual is not None else ""
        ref = str(ref) if ref is not None else ""

        try:
            if ref_type == "number":
                actual_num = float(actual)
                ref_num = float(ref)
                if op == "<":
                    return actual_num < ref_num
                elif op == "<=":
                    return actual_num <= ref_num
                elif op == ">":
                    return actual_num > ref_num
                elif op == ">=":
                    return actual_num >= ref_num
                elif op in ("=", "=="):
                    return actual_num == ref_num
                elif op == "!=":
                    return actual_num != ref_num
            elif ref_type == "boolean":
                actual_bool = actual.lower() in ("true", "1", "yes")
                ref_bool = ref.lower() in ("true", "1", "yes")
                if op in ("=", "=="):
                    return actual_bool == ref_bool
                elif op == "!=":
                    return actual_bool != ref_bool
            else:
                if op in ("=", "=="):
                    return actual.strip().lower() == ref.strip().lower()
                elif op == "!=":
                    return actual.strip().lower() != ref.strip().lower()
        except (ValueError, TypeError):
            if op in ("=", "=="):
                return actual == ref
            elif op == "!=":
                return actual != ref

        return False

    # =========================================================================
    # Guide Selection (조건부)
    # =========================================================================

    def select_guides(self, step_id: str, state: ConversationState, all_guides: list[dict]) -> list[dict]:
        """현재 상태에 따라 적절한 Guide 선택"""
        if not all_guides:
            return []

        if step_id in GUIDE_SELECTION_RULES:
            rule = GUIDE_SELECTION_RULES[step_id]
            condition_var = rule["conditionVar"]
            current_value = state.get_slot(condition_var)

            if current_value and current_value in rule["mapping"]:
                allowed_ids = rule["mapping"][current_value]
                filtered = [g for g in all_guides if g.get("id") in allowed_ids]
                if filtered:
                    return filtered

        return all_guides
