"""
schema/ingestion.py - TTL → Neo4j 변환용 Ingestion 쿼리

MERGE 쿼리, Relationship 생성, Embedding 업데이트,
Transition/DecisionRule 생성 쿼리 및 extract_local_id 유틸.
"""
from __future__ import annotations

# =============================================================================
# Ingestion 쿼리 (TTL -> Neo4j)
# =============================================================================

QUERY_MERGE_PERSONA = """
MERGE (p:Persona {id: $id})
SET p.name = $name, p.description = $desc, p.tags = $tags
RETURN p.id AS id
"""

QUERY_MERGE_SCENARIO = """
MERGE (s:Scenario {id: $id})
SET s.name = $name, s.desc = $desc, s.domain = $domain, s.stage_model = $stageModel
RETURN s.id AS id
"""

QUERY_MERGE_STEP = """
MERGE (st:Step {id: $id})
SET st.desc = $desc, st.type = $stepType
RETURN st.id AS id
"""

QUERY_MERGE_CHECKITEM = """
MERGE (ci:CheckItem {id: $id})
SET ci.name = $name, ci.dataType = $dataType
RETURN ci.id AS id
"""

QUERY_MERGE_SURGERY = """
MERGE (su:Surgery {id: $id})
SET su.name = $name, su.desc = $desc, su.category = $category
RETURN su.id AS id
"""

QUERY_MERGE_SIDEEFFECT = """
MERGE (se:SideEffect {id: $id})
SET se.name = $name, se.desc = $desc
RETURN se.id AS id
"""

QUERY_MERGE_GUIDE = """
MERGE (g:Guide {id: $id})
SET g.desc = $desc
RETURN g.id AS id
"""

QUERY_MERGE_PROGRAM = """
MERGE (p:Program {id: $id})
SET p.name = $name, p.description = $desc, p.category = $category
RETURN p.id AS id
"""

QUERY_MERGE_OPTION = """
MERGE (o:Option {id: $id})
SET o.value = $value, o.desc = $desc
RETURN o.id AS id
"""

# --- Relationship 생성 ---

QUERY_CREATE_REL_HAS_SCENARIO = """
MATCH (p:Persona {id: $personaId})
MATCH (s:Scenario {id: $scenarioId})
MERGE (p)-[:HAS_SCENARIO]->(s)
"""

QUERY_CREATE_REL_HAS_STEP = """
MATCH (s:Scenario {id: $scenarioId})
MATCH (st:Step {id: $stepId})
MERGE (s)-[:HAS_STEP]->(st)
"""

QUERY_CREATE_REL_STEP_TO = """
MATCH (from:Step {id: $fromStepId})
MATCH (to:Step {id: $toStepId})
MERGE (from)-[:TO]->(to)
"""

# 레거시 호환
QUERY_CREATE_REL_STARTS_AT = """
MATCH (s:Scenario {id: $scenarioId})
MATCH (st:Step {id: $stepId})
MERGE (s)-[:startsAt]->(st)
"""

QUERY_CREATE_REL_LEADS_TO = """
MATCH (from:Step {id: $fromStepId})
MATCH (to:Step {id: $toStepId})
MERGE (from)-[:leadsTo]->(to)
"""

QUERY_CREATE_REL_CHECKS = """
MATCH (st:Step {id: $stepId})
MATCH (ci:CheckItem {id: $checkItemId})
MERGE (st)-[:CHECKS]->(ci)
"""

QUERY_CREATE_REL_ASKS_FOR = """
MATCH (s:Scenario {id: $scenarioId})
MATCH (ci:CheckItem {id: $checkItemId})
MERGE (s)-[:ASKS_FOR]->(ci)
"""

QUERY_CREATE_REL_GUIDED_BY = """
MATCH (st:Step {id: $stepId})
MATCH (g:Guide {id: $guideId})
MERGE (st)-[:GUIDED_BY]->(g)
"""

QUERY_CREATE_REL_RECOMMENDS = """
MATCH (st:Step {id: $stepId})
MATCH (p:Program {id: $programId})
MERGE (st)-[:RECOMMENDS]->(p)
"""

QUERY_CREATE_REL_REFERENCE = """
MATCH (st:Step {id: $stepId})
MATCH (ci:CheckItem {id: $checkItemId})
MERGE (st)-[:REFERENCE]->(ci)
"""

QUERY_CREATE_REL_HAS_OPTION = """
MATCH (ci:CheckItem {id: $checkItemId})
MATCH (o:Option {id: $optionId})
MERGE (ci)-[:HAS_OPTION]->(o)
"""

QUERY_CREATE_REL_HAS_SIDE_EFFECT = """
MATCH (p:Program {id: $programId})
MATCH (se:SideEffect {id: $sideEffectId})
MERGE (p)-[:HAS_SIDE_EFFECT]->(se)
"""

QUERY_CREATE_REL_CAUSE_SIDEEFFECT = """
MATCH (su:Surgery {id: $surgeryId})
MATCH (se:SideEffect {id: $sideEffectId})
MERGE (su)-[:causeSideEffect]->(se)
"""

# --- Embedding 업데이트 ---

QUERY_UPDATE_EMBEDDING = """
MATCH (n {id: $id})
SET n.embedding = $embedding
RETURN n.id AS id
"""

# =============================================================================
# Transition/DecisionRule 생성 쿼리
# =============================================================================

QUERY_MERGE_TRANSITION = """
MERGE (t:Transition {id: $id})
SET t.desc = $desc, t.priority = $priority, t.isDefault = $isDefault
RETURN t.id AS id
"""

QUERY_MERGE_DECISION_RULE = """
MERGE (r:DecisionRule {id: $id})
SET r.desc = $desc
RETURN r.id AS id
"""

QUERY_MERGE_CONDITION_GROUP = """
MERGE (g:ConditionGroup {id: $id})
RETURN g.id AS id
"""

QUERY_MERGE_CONDITION = """
MERGE (c:Condition {id: $id})
SET c.input = $input, c.op = $op, c.ref = $ref, c.refType = $refType,
    c.missingPolicy = $missingPolicy, c.desc = $desc
RETURN c.id AS id
"""

QUERY_MERGE_THRESHOLD = """
MERGE (th:Threshold {id: $id})
SET th.name = $name, th.value = $value
RETURN th.id AS id
"""

# --- Transition 관계 생성 ---

QUERY_CREATE_REL_HAS_TRANSITION = """
MATCH (st:Step {id: $stepId})
MATCH (t:Transition {id: $transitionId})
MERGE (st)-[:HAS_TRANSITION]->(t)
"""

QUERY_CREATE_REL_TRANSITION_TO = """
MATCH (t:Transition {id: $transitionId})
MATCH (st:Step {id: $stepId})
MERGE (t)-[:TO]->(st)
"""

QUERY_CREATE_REL_GUARDED_BY = """
MATCH (t:Transition {id: $transitionId})
MATCH (r:DecisionRule {id: $ruleId})
MERGE (t)-[:GUARDED_BY]->(r)
"""

QUERY_CREATE_REL_WHEN = """
MATCH (r:DecisionRule {id: $ruleId})
MATCH (g:ConditionGroup {id: $groupId})
MERGE (r)-[:WHEN]->(g)
"""

QUERY_CREATE_REL_HAS_CONDITION = """
MATCH (g:ConditionGroup {id: $groupId})
MATCH (c:Condition {id: $conditionId})
MERGE (g)-[:HAS_CONDITION]->(c)
"""

QUERY_CREATE_REL_COMPARES_TO = """
MATCH (c:Condition {id: $conditionId})
MATCH (th:Threshold {id: $thresholdId})
MERGE (c)-[:COMPARES_TO]->(th)
"""


# =============================================================================
# 유틸리티 함수
# =============================================================================

def extract_local_id(uri: str) -> str:
    """URI에서 로컬 ID 추출 (# 또는 / 뒤의 부분)"""
    if "#" in uri:
        return uri.split("#")[-1]
    return uri.split("/")[-1]
