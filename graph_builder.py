"""
graph_builder.py - YAML config → Neo4j 그래프 빌드

ConfigLoader에서 로드한 설정을 Neo4j에 MERGE 쿼리로 적재.
schema.py의 MERGE 쿼리를 재사용.
"""

from __future__ import annotations

import logging
from typing import Any

from neo4j import Driver

import schema as S

logger = logging.getLogger(__name__)


class GraphBuilder:
    """YAML config → Neo4j 그래프 빌더."""

    def __init__(self, driver: Driver, config: dict) -> None:
        self.driver = driver
        self.config = config
        self._stats: dict[str, int] = {}

    # ------------------------------------------------------------------
    # 공개 API
    # ------------------------------------------------------------------

    def build(
        self,
        clear_first: bool = False,
        create_embeddings: bool = True,
    ) -> dict:
        """
        전체 그래프 빌드.

        Args:
            clear_first: True면 기존 데이터 삭제 후 재빌드
            create_embeddings: True면 빌드 후 임베딩 생성

        Returns:
            빌드 통계 dict (노드/관계 수)
        """
        self._stats = {}

        if clear_first:
            self._clear_graph()

        # 1. Schema (constraints + indexes)
        self._create_schema()

        # 2. 노드 생성
        self._build_personas()
        self._build_scenarios()
        self._build_steps()
        self._build_check_items()
        self._build_guides()
        self._build_options()
        self._build_programs()
        self._build_side_effects()
        self._build_conditions()
        self._build_decision_rules()
        self._build_transitions()

        # 3. 관계 생성
        self._build_persona_scenario_rels()
        self._build_scenario_step_rels()
        self._build_step_order_rels()
        self._build_step_checks_rels()
        self._build_step_guide_rels()
        self._build_step_program_rels()
        self._build_step_reference_rels()
        self._build_checkitem_option_rels()
        self._build_scenario_asks_for_rels()
        self._build_branching_rels()
        self._build_considers_rels()
        self._build_knowledge_rels()

        # 4. 임베딩 (선택)
        if create_embeddings:
            self._create_embeddings()

        logger.info("Build complete: %s", self._stats)
        return dict(self._stats)

    def validate(self) -> list[str]:
        """빌드 전 config 사전 검증 (config_loader.validate()와 별개로 DB 관련 검증)."""
        errors: list[str] = []
        # 향후 DB 연결 확인, 기존 데이터 충돌 검사 등 추가 가능
        try:
            with self.driver.session() as session:
                session.run("RETURN 1")
        except Exception as e:
            errors.append(f"Neo4j 연결 실패: {e}")
        return errors

    # ------------------------------------------------------------------
    # Schema
    # ------------------------------------------------------------------

    def _create_schema(self) -> None:
        """Constraint/Index 생성."""
        with self.driver.session() as session:
            for q in S.SCHEMA_QUERIES:
                session.run(q)
            for q in S.VECTOR_INDEX_QUERIES:
                try:
                    session.run(q)
                except Exception:
                    logger.debug("Vector index already exists or not supported")
        logger.info("Schema constraints/indexes created")

    def _clear_graph(self) -> None:
        """기존 그래프 데이터 전부 삭제."""
        with self.driver.session() as session:
            result = session.run("MATCH (n) DETACH DELETE n RETURN count(n) AS cnt")
            cnt = result.single()["cnt"]
        logger.warning("Cleared graph: %d nodes deleted", cnt)
        self._stats["cleared_nodes"] = cnt

    # ------------------------------------------------------------------
    # 노드 빌드
    # ------------------------------------------------------------------

    def _build_personas(self) -> None:
        count = 0
        with self.driver.session() as session:
            for pid, p in self.config.get("personas", {}).items():
                tags = p.get("tags", [])
                if isinstance(tags, str):
                    tags = [t.strip() for t in tags.split(",")]
                session.run(
                    S.QUERY_MERGE_PERSONA,
                    id=pid,
                    name=p.get("name", ""),
                    desc=p.get("description", ""),
                    tags=tags,
                )
                count += 1
        self._stats["personas"] = count
        logger.info("Built %d Persona nodes", count)

    def _build_scenarios(self) -> None:
        count = 0
        with self.driver.session() as session:
            for sid, s in self.config.get("scenarios", {}).items():
                session.run(
                    S.QUERY_MERGE_SCENARIO,
                    id=sid,
                    name=s.get("name", ""),
                    desc=s.get("description", ""),
                    domain=s.get("domain", ""),
                    stageModel=s.get("stage_model", ""),
                )
                count += 1
        self._stats["scenarios"] = count
        logger.info("Built %d Scenario nodes", count)

    def _build_steps(self) -> None:
        count = 0
        with self.driver.session() as session:
            for step_id, step in self.config.get("steps", {}).items():
                session.run(
                    S.QUERY_MERGE_STEP,
                    id=step_id,
                    desc=step.get("description", ""),
                    stepType=step.get("type"),
                )
                count += 1
        self._stats["steps"] = count
        logger.info("Built %d Step nodes", count)

    def _build_check_items(self) -> None:
        count = 0
        with self.driver.session() as session:
            for ci_id, ci in self.config.get("check_items", {}).items():
                session.run(
                    S.QUERY_MERGE_CHECKITEM,
                    id=ci_id,
                    name=ci.get("name", ""),
                    dataType=ci.get("dataType", "string"),
                )
                count += 1
        self._stats["check_items"] = count
        logger.info("Built %d CheckItem nodes", count)

    def _build_guides(self) -> None:
        count = 0
        with self.driver.session() as session:
            for gid, g in self.config.get("guides", {}).items():
                session.run(
                    S.QUERY_MERGE_GUIDE,
                    id=gid,
                    desc=g.get("description", ""),
                )
                count += 1
        self._stats["guides"] = count
        logger.info("Built %d Guide nodes", count)

    def _build_options(self) -> None:
        count = 0
        with self.driver.session() as session:
            for oid, o in self.config.get("options", {}).items():
                session.run(
                    S.QUERY_MERGE_OPTION,
                    id=oid,
                    value=o.get("value", ""),
                    desc=o.get("description", ""),
                )
                count += 1
        self._stats["options"] = count
        logger.info("Built %d Option nodes", count)

    def _build_programs(self) -> None:
        count = 0
        with self.driver.session() as session:
            for pid, p in self.config.get("programs", {}).items():
                session.run(
                    S.QUERY_MERGE_PROGRAM,
                    id=pid,
                    name=p.get("name", ""),
                    desc=p.get("description", ""),
                    category=p.get("category", ""),
                )
                count += 1
        self._stats["programs"] = count
        logger.info("Built %d Program nodes", count)

    def _build_side_effects(self) -> None:
        count = 0
        with self.driver.session() as session:
            # program_side_effects
            for se_id, se in self.config.get("program_side_effects", {}).items():
                session.run(
                    S.QUERY_MERGE_SIDEEFFECT,
                    id=se_id,
                    name=se.get("name", ""),
                    desc=se.get("description", ""),
                )
                count += 1
            # surgery_side_effects
            for se_id, se in self.config.get("surgery_side_effects", {}).items():
                session.run(
                    S.QUERY_MERGE_SIDEEFFECT,
                    id=se_id,
                    name=se.get("name", ""),
                    desc=se.get("description", ""),
                )
                count += 1
        self._stats["side_effects"] = count
        logger.info("Built %d SideEffect nodes", count)

    def _build_conditions(self) -> None:
        count = 0
        with self.driver.session() as session:
            for cid, c in self.config.get("conditions", {}).items():
                session.run(
                    S.QUERY_MERGE_CONDITION,
                    id=cid,
                    input=c.get("input", ""),
                    op=c.get("op", ""),
                    ref=c.get("ref", ""),
                    refType=c.get("refType", "string"),
                    missingPolicy=c.get("missingPolicy", "UNKNOWN"),
                    desc=c.get("description", ""),
                )
                count += 1
        self._stats["conditions"] = count
        logger.info("Built %d Condition nodes", count)

    def _build_decision_rules(self) -> None:
        count = 0
        or_rules = set(self.config.get("or_logic_rules", []))
        with self.driver.session() as session:
            for rid, r in self.config.get("decision_rules", {}).items():
                session.run(
                    S.QUERY_MERGE_DECISION_RULE,
                    id=rid,
                    desc=r.get("description", ""),
                    logic="OR" if rid in or_rules else "AND",
                )
                count += 1
        self._stats["decision_rules"] = count
        logger.info("Built %d DecisionRule nodes", count)

    def _build_transitions(self) -> None:
        """branching에서 Transition 노드 추출하여 생성.

        인라인 조건(rule_id 없이 conditions만 있는 경우)은
        자동으로 DecisionRule/Condition 노드를 생성한다.
        """
        trans_count = 0
        auto_rule_count = 0
        auto_cond_count = 0
        seen: set[str] = set()

        with self.driver.session() as session:
            for _step_id, rules in self.config.get("branching", {}).items():
                for rule in rules:
                    tid = rule.get("transition_id")
                    if tid and tid not in seen:
                        seen.add(tid)
                        session.run(
                            S.QUERY_MERGE_TRANSITION,
                            id=tid,
                            desc="",
                            priority=rule.get("priority", 0),
                            isDefault=rule.get("default", False),
                            protocolMode=rule.get("protocol_mode", ""),
                        )
                        trans_count += 1

                    # 인라인 조건 → auto DecisionRule/Condition 생성
                    if rule.get("conditions") and not rule.get("rule_id"):
                        auto_rule_id = "_auto_{}".format(tid)
                        session.run(
                            S.QUERY_MERGE_DECISION_RULE,
                            id=auto_rule_id,
                            desc="auto-generated",
                            logic="AND",
                        )
                        auto_rule_count += 1

                        for cond in rule["conditions"]:
                            cond_id = "_inline_{}_{}_{}" .format(
                                cond["var"], cond["op"], cond["ref"],
                            )
                            session.run(
                                S.QUERY_MERGE_CONDITION,
                                id=cond_id,
                                input=cond["var"],
                                op=cond["op"],
                                ref=str(cond["ref"]),
                                refType="string",
                                missingPolicy="UNKNOWN",
                                desc="",
                            )
                            session.run(
                                "MATCH (r:DecisionRule {id: $rid}) "
                                "MATCH (c:Condition {id: $cid}) "
                                "MERGE (r)-[:CONSIDERS]->(c)",
                                rid=auto_rule_id,
                                cid=cond_id,
                            )
                            auto_cond_count += 1

        self._stats["transitions"] = trans_count
        if auto_rule_count:
            self._stats["auto_decision_rules"] = auto_rule_count
            self._stats["auto_conditions"] = auto_cond_count
        logger.info(
            "Built %d Transition nodes (%d auto rules, %d auto conditions)",
            trans_count, auto_rule_count, auto_cond_count,
        )

    # ------------------------------------------------------------------
    # 관계 빌드
    # ------------------------------------------------------------------

    def _build_persona_scenario_rels(self) -> None:
        count = 0
        with self.driver.session() as session:
            for pid, p in self.config.get("personas", {}).items():
                for sid in p.get("scenarios", []):
                    session.run(S.QUERY_CREATE_REL_HAS_SCENARIO, personaId=pid, scenarioId=sid)
                    count += 1
        self._stats["rel_has_scenario"] = count

    def _build_scenario_step_rels(self) -> None:
        count = 0
        with self.driver.session() as session:
            for sid, s in self.config.get("scenarios", {}).items():
                for step_id in s.get("steps", []):
                    session.run(S.QUERY_CREATE_REL_HAS_STEP, scenarioId=sid, stepId=step_id)
                    count += 1
        self._stats["rel_has_step"] = count

    def _build_step_order_rels(self) -> None:
        count = 0
        with self.driver.session() as session:
            for from_id, to_val in self.config.get("step_order", {}).items():
                targets = to_val if isinstance(to_val, list) else [to_val]
                for to_id in targets:
                    session.run(S.QUERY_CREATE_REL_STEP_TO, fromStepId=from_id, toStepId=to_id)
                    count += 1
        self._stats["rel_step_to"] = count

    def _build_step_checks_rels(self) -> None:
        count = 0
        with self.driver.session() as session:
            for step_id, step in self.config.get("steps", {}).items():
                for ci_id in step.get("checks", []):
                    session.run(S.QUERY_CREATE_REL_CHECKS, stepId=step_id, checkItemId=ci_id)
                    count += 1
        self._stats["rel_checks"] = count

    def _build_step_guide_rels(self) -> None:
        count = 0
        with self.driver.session() as session:
            for step_id, step in self.config.get("steps", {}).items():
                for gid in step.get("guides", []):
                    session.run(S.QUERY_CREATE_REL_GUIDED_BY, stepId=step_id, guideId=gid)
                    count += 1
        self._stats["rel_guided_by"] = count

    def _build_step_program_rels(self) -> None:
        count = 0
        with self.driver.session() as session:
            for step_id, step in self.config.get("steps", {}).items():
                for pid in step.get("programs", []):
                    session.run(S.QUERY_CREATE_REL_RECOMMENDS, stepId=step_id, programId=pid)
                    count += 1
        self._stats["rel_recommends"] = count

    def _build_step_reference_rels(self) -> None:
        count = 0
        with self.driver.session() as session:
            for step_id, step in self.config.get("steps", {}).items():
                for ci_id in step.get("reference_slots", []):
                    session.run(S.QUERY_CREATE_REL_REFERENCE, stepId=step_id, checkItemId=ci_id)
                    count += 1
        self._stats["rel_reference"] = count

    def _build_checkitem_option_rels(self) -> None:
        count = 0
        with self.driver.session() as session:
            for ci_id, ci in self.config.get("check_items", {}).items():
                for opt_id in ci.get("options", []):
                    session.run(S.QUERY_CREATE_REL_HAS_OPTION, checkItemId=ci_id, optionId=opt_id)
                    count += 1
        self._stats["rel_has_option"] = count

    def _build_scenario_asks_for_rels(self) -> None:
        """Scenario → CheckItem :ASKS_FOR 자동 집계 (시나리오의 모든 Step에서 CHECKS 합산)."""
        count = 0
        scenarios = self.config.get("scenarios", {})
        steps = self.config.get("steps", {})

        with self.driver.session() as session:
            for sid, s in scenarios.items():
                all_checks: set[str] = set()
                for step_id in s.get("steps", []):
                    step = steps.get(step_id, {})
                    all_checks.update(step.get("checks", []))
                for ci_id in all_checks:
                    session.run(S.QUERY_CREATE_REL_ASKS_FOR, scenarioId=sid, checkItemId=ci_id)
                    count += 1
        self._stats["rel_asks_for"] = count

    def _build_branching_rels(self) -> None:
        """
        Branching rules → HAS_TRANSITION, GUARDED_BY, TRANSITION_TO 관계.
        """
        ht_count = 0
        gb_count = 0
        tt_count = 0

        with self.driver.session() as session:
            for step_id, rules in self.config.get("branching", {}).items():
                for rule in rules:
                    tid = rule.get("transition_id")
                    if not tid:
                        continue

                    # Step -[:HAS_TRANSITION]-> Transition
                    session.run(
                        S.QUERY_CREATE_REL_HAS_TRANSITION,
                        stepId=step_id,
                        transitionId=tid,
                    )
                    ht_count += 1

                    # Transition -[:TO]-> target Step
                    target = rule.get("target_step")
                    if target:
                        session.run(
                            S.QUERY_CREATE_REL_TRANSITION_TO,
                            transitionId=tid,
                            stepId=target,
                        )
                        tt_count += 1

                    # Transition -[:GUARDED_BY]-> DecisionRule
                    rid = rule.get("rule_id")
                    if not rid and rule.get("conditions"):
                        rid = "_auto_{}".format(tid)
                    if rid:
                        session.run(
                            S.QUERY_CREATE_REL_GUARDED_BY,
                            transitionId=tid,
                            ruleId=rid,
                        )
                        gb_count += 1

        self._stats["rel_has_transition"] = ht_count
        self._stats["rel_guarded_by"] = gb_count
        self._stats["rel_transition_to"] = tt_count

    def _build_considers_rels(self) -> None:
        """rule_condition_map → DecisionRule -[:CONSIDERS]-> Condition 관계 직접 생성."""
        count = 0
        with self.driver.session() as session:
            for rid, cond_ids in self.config.get("rule_condition_map", {}).items():
                for cid in cond_ids:
                    # CONSIDERS 관계 생성 쿼리
                    session.run(
                        """
                        MATCH (r:DecisionRule {id: $ruleId})
                        MATCH (c:Condition {id: $conditionId})
                        MERGE (r)-[:CONSIDERS]->(c)
                        """,
                        ruleId=rid,
                        conditionId=cid,
                    )
                    count += 1
        self._stats["rel_considers"] = count
        logger.info("Built %d CONSIDERS relationships", count)

    def _build_knowledge_rels(self) -> None:
        """Surgery/Program → SideEffect 관계."""
        count = 0
        with self.driver.session() as session:
            # Surgery → SideEffect
            for surg_id, surg in self.config.get("surgeries", {}).items():
                for se_id in surg.get("side_effects", []):
                    session.run(
                        S.QUERY_CREATE_REL_CAUSE_SIDEEFFECT,
                        surgeryId=surg_id,
                        sideEffectId=se_id,
                    )
                    count += 1
            # Program → SideEffect
            for prog_id, prog in self.config.get("programs", {}).items():
                for se_id in prog.get("side_effects", []):
                    session.run(
                        S.QUERY_CREATE_REL_HAS_SIDE_EFFECT,
                        programId=prog_id,
                        sideEffectId=se_id,
                    )
                    count += 1
        self._stats["rel_side_effects"] = count

    # ------------------------------------------------------------------
    # 임베딩
    # ------------------------------------------------------------------

    def _create_embeddings(self) -> None:
        """core.py의 _create_embeddings() 재사용."""
        try:
            from core import SC301Core

            core = SC301Core.__new__(SC301Core)
            core.driver = self.driver
            core._create_embeddings()
            logger.info("Embeddings created")
        except Exception as e:
            logger.warning("Embedding creation skipped: %s", e)
