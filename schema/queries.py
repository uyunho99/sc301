"""
schema/queries.py - Neo4j 스키마 정의 및 Flow 조회 쿼리

TTL 온톨로지를 Neo4j로 변환하기 위한 스키마 정의,
Flow 엔진에서 사용하는 Cypher 쿼리 상수 모음.

실제 그래프 구조 (2025-01 Ontology 기준):
  Persona -[:HAS_SCENARIO]-> Scenario -[:HAS_STEP]-> Step
  Step -[:TO]-> Step                      (순차 흐름)
  Step -[:CHECKS]-> CheckItem             (수집 항목)
  Step -[:GUIDED_BY]-> Guide              (가이드 문구)
  Step -[:RECOMMENDS]-> Program           (추천 프로그램)
  Step -[:REFERENCE]-> CheckItem          (참조용 슬롯)
  Scenario -[:ASKS_FOR]-> CheckItem       (시나리오 전체 수집 항목)
  CheckItem -[:HAS_OPTION]-> Option       (선택지)
  Program -[:HAS_SIDE_EFFECT]-> SideEffect
  Surgery -[:causeSideEffect]-> SideEffect

  Transition -[:GUARDED_BY]-> DecisionRule -[:CONSIDERS]-> Condition  (권장, 1:N 정확한 매핑)
  Transition -[:GUARDED_BY]-> DecisionRule -[:WHEN]-> ConditionGroup -[:HAS_CONDITION]-> Condition  (레거시)
  (Transition 노드는 Step 간 분기 메타데이터로 존재하며, Step에 직접 연결되지 않음.
   실제 Step 전이는 TO 관계 + DecisionRule 조건 평가로 결정.)
"""
from __future__ import annotations

# =============================================================================
# TTL Namespace 정의
# =============================================================================

TTL_NAMESPACES = {
    "ont": "http://www.co-ode.org/ontologies/ont.owl#",
    "sample": "http://dcx-lab-sc301/chatbot/ontology/sample#",
    "webprotege": "http://webprotege.stanford.edu/",
}

# =============================================================================
# Schema 생성 쿼리 (Constraints & Indexes)
# =============================================================================

SCHEMA_QUERIES = [
    # --- Uniqueness Constraints ---
    "CREATE CONSTRAINT IF NOT EXISTS FOR (p:Persona) REQUIRE p.id IS UNIQUE",
    "CREATE CONSTRAINT IF NOT EXISTS FOR (s:Scenario) REQUIRE s.id IS UNIQUE",
    "CREATE CONSTRAINT IF NOT EXISTS FOR (st:Step) REQUIRE st.id IS UNIQUE",
    "CREATE CONSTRAINT IF NOT EXISTS FOR (ci:CheckItem) REQUIRE ci.id IS UNIQUE",
    "CREATE CONSTRAINT IF NOT EXISTS FOR (su:Surgery) REQUIRE su.id IS UNIQUE",
    "CREATE CONSTRAINT IF NOT EXISTS FOR (se:SideEffect) REQUIRE se.id IS UNIQUE",
    "CREATE CONSTRAINT IF NOT EXISTS FOR (g:Guide) REQUIRE g.id IS UNIQUE",
    "CREATE CONSTRAINT IF NOT EXISTS FOR (pr:Program) REQUIRE pr.id IS UNIQUE",
    "CREATE CONSTRAINT IF NOT EXISTS FOR (o:Option) REQUIRE o.id IS UNIQUE",

    # --- Transition/DecisionRule ---
    "CREATE CONSTRAINT IF NOT EXISTS FOR (t:Transition) REQUIRE t.id IS UNIQUE",
    "CREATE CONSTRAINT IF NOT EXISTS FOR (dr:DecisionRule) REQUIRE dr.id IS UNIQUE",
    "CREATE CONSTRAINT IF NOT EXISTS FOR (cg:ConditionGroup) REQUIRE cg.id IS UNIQUE",
    "CREATE CONSTRAINT IF NOT EXISTS FOR (c:Condition) REQUIRE c.id IS UNIQUE",
    "CREATE CONSTRAINT IF NOT EXISTS FOR (th:Threshold) REQUIRE th.id IS UNIQUE",
]

# Vector Index 생성 쿼리 (별도 실행 필요)
VECTOR_INDEX_QUERIES = [
    """
    CREATE VECTOR INDEX surgery_embedding IF NOT EXISTS
    FOR (s:Surgery)
    ON s.embedding
    OPTIONS {indexConfig: {
        `vector.dimensions`: 1536,
        `vector.similarity_function`: 'cosine'
    }}
    """,
    """
    CREATE VECTOR INDEX step_embedding IF NOT EXISTS
    FOR (s:Step)
    ON s.embedding
    OPTIONS {indexConfig: {
        `vector.dimensions`: 1536,
        `vector.similarity_function`: 'cosine'
    }}
    """,
    """
    CREATE VECTOR INDEX checkitem_embedding IF NOT EXISTS
    FOR (c:CheckItem)
    ON c.embedding
    OPTIONS {indexConfig: {
        `vector.dimensions`: 1536,
        `vector.similarity_function`: 'cosine'
    }}
    """,
]

# =============================================================================
# Flow 관련 쿼리
# =============================================================================

# --- Persona/Scenario 조회 ---

QUERY_ALL_PERSONAS = """
MATCH (p:Persona)
OPTIONAL MATCH (p)-[:HAS_SCENARIO]->(s:Scenario)
RETURN p.id AS personaId, p.name AS name, p.description AS desc, p.tags AS tags,
       collect(s.id) AS scenarioIds
"""

QUERY_PERSONA_BY_ID = """
MATCH (p:Persona {id: $personaId})
OPTIONAL MATCH (p)-[:HAS_SCENARIO]->(s:Scenario)
RETURN p.id AS personaId, p.name AS name, p.description AS desc, p.tags AS tags,
       collect({id: s.id, name: s.name, domain: s.domain}) AS scenarios
"""

QUERY_SCENARIO_BY_ID = """
MATCH (s:Scenario {id: $scenarioId})
OPTIONAL MATCH (s)-[:HAS_STEP]->(firstStep:Step)
  WHERE NOT ()-[:TO]->(firstStep)
OPTIONAL MATCH (s)-[:ASKS_FOR]->(ci:CheckItem)
RETURN s.id AS scenarioId, s.name AS name, s.desc AS desc,
       s.domain AS domain, s.stage_model AS stageModel,
       firstStep.id AS startStepId,
       collect(DISTINCT ci.name) AS requiredSlots
"""

QUERY_SCENARIO_START_STEP = """
MATCH (s:Scenario {id: $scenarioId})-[:HAS_STEP]->(step:Step)
WHERE NOT ()-[:TO]->(step)
RETURN step.id AS stepId
LIMIT 1
"""

# --- Step 조회 ---

QUERY_STEP_BY_ID = """
MATCH (st:Step {id: $stepId})
OPTIONAL MATCH (st)-[:CHECKS]->(ci:CheckItem)
OPTIONAL MATCH (st)-[:GUIDED_BY]->(g:Guide)
OPTIONAL MATCH (st)-[:RECOMMENDS]->(pr:Program)
OPTIONAL MATCH (st)-[:REFERENCE]->(ref:CheckItem)
RETURN st.id AS stepId, st.desc AS desc, st.type AS stepType,
       collect(DISTINCT {
           id: ci.id,
           name: ci.name,
           variableName: ci.id,
           dataType: ci.dataType
       }) AS checkItems,
       collect(DISTINCT {id: g.id, desc: g.desc}) AS guides,
       collect(DISTINCT {id: pr.id, name: pr.name, category: pr.category}) AS programs,
       collect(DISTINCT ref.id) AS referenceSlots
"""

QUERY_STEP_CHECKS = """
MATCH (st:Step {id: $stepId})-[:CHECKS]->(ci:CheckItem)
RETURN ci.id AS id, ci.name AS name, ci.id AS variableName, ci.dataType AS dataType
"""

# --- Step 전이 (TO 기반) ---

QUERY_NEXT_STEPS_BY_TO = """
MATCH (cur:Step {id: $stepId})-[:TO]->(next:Step)
RETURN next.id AS nextStepId, next.desc AS desc, next.type AS stepType
"""

# leadsTo fallback (레거시 호환)
QUERY_NEXT_STEP_BY_LEADS_TO = """
MATCH (cur:Step {id: $stepId})-[:leadsTo]->(next:Step)
RETURN next.id AS nextStepId, next.desc AS desc, next.type AS stepType
"""

# --- Transition / DecisionRule 조회 ---

QUERY_DECISION_RULE_CONDITIONS = """
MATCH (r:DecisionRule {id: $ruleId})-[:WHEN]->(g:ConditionGroup)-[:HAS_CONDITION]->(c:Condition)
RETURN g.id AS logic,
       collect({
           condId: c.id,
           input: c.input,
           op: c.op,
           ref: c.ref,
           refType: c.refType,
           missingPolicy: c.missingPolicy,
           desc: c.desc
       }) AS conditions
"""

# --- CONSIDERS 기반 조건 조회 (권장 경로) ---

QUERY_RULE_CONDITIONS_VIA_CONSIDERS = """
MATCH (r:DecisionRule {id: $ruleId})-[:CONSIDERS]->(c:Condition)
RETURN collect({
    condId: c.id,
    input: c.input,
    op: c.op,
    ref: c.ref,
    refType: c.refType,
    missingPolicy: c.missingPolicy,
    desc: c.desc
}) AS conditions
"""

QUERY_HAS_CONSIDERS = """
MATCH ()-[r:CONSIDERS]->()
RETURN count(r) > 0 AS hasConsiders
LIMIT 1
"""

# --- CheckItem Option 조회 ---

QUERY_CHECKITEM_OPTIONS = """
MATCH (ci:CheckItem {id: $checkItemId})-[:HAS_OPTION]->(o:Option)
RETURN o.id AS optionId, o.value AS value, o.desc AS desc
ORDER BY o.value
"""

# --- 시나리오 전체 CheckItem 조회 (Look-ahead 추출용) ---

QUERY_SCENARIO_ALL_CHECKS = """
MATCH (s:Scenario {id: $scenarioId})-[:ASKS_FOR]->(ci:CheckItem)
RETURN ci.id AS id, ci.name AS name, ci.id AS variableName, ci.dataType AS dataType
"""

# =============================================================================
# Vector Search 쿼리
# =============================================================================

QUERY_VECTOR_SEARCH_SURGERY = """
CALL db.index.vector.queryNodes('surgery_embedding', $k, $embedding)
YIELD node, score
RETURN node.id AS id, node.name AS name, node.desc AS desc,
       node.category AS category, score
ORDER BY score DESC
"""

QUERY_VECTOR_SEARCH_STEP = """
CALL db.index.vector.queryNodes('step_embedding', $k, $embedding)
YIELD node, score
RETURN node.id AS id, node.desc AS desc, node.type AS stepType, score
ORDER BY score DESC
"""
