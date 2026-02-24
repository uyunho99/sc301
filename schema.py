"""
schema.py - Neo4j 스키마 및 Cypher 쿼리 모음

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
# 분기 규칙 매핑 (Transition ID -> 관련 DecisionRule 및 대상 Step)
#
# 실제 DB에서 Transition이 Step에 HAS_TRANSITION으로 연결되지 않으므로,
# 분기가 필요한 Step과 Transition/Rule을 매핑하는 정적 라우팅 테이블.
# docx 온톨로지 기반 + 실제 DB 데이터 기준.
# =============================================================================

# 각 분기점 Step에서의 Transition 규칙
# format: { sourceStepId: [ { transitionId, ruleId, targetStepId, priority, isDefault } ] }
BRANCHING_RULES = {
    # === Persona 1 (slimBody): BMI 기준 분기 ===
    # p1InformSurgery에서 bmi >= 23 (STANDARD) vs bmi < 23 (LOW-FAT)
    "p1InformSurgery": [
        {
            "transitionId": "bmiPathStandard",
            "ruleId": "ruleBodyFatHigh",
            "targetStepId": "p1InformInfo",  # STANDARD 경로
            "priority": 10,
            "isDefault": False,
        },
        {
            "transitionId": "bmiPathLowFat",
            "ruleId": "ruleBodyFatLow",
            "targetStepId": "p1InformInfo",  # LOW-FAT 경로 (같은 Step, Guide가 다름)
            "priority": 20,
            "isDefault": False,
        },
        {
            "transitionId": "bmiPathDefault",
            "ruleId": None,
            "targetStepId": "p1InformInfo",  # Default: BMI 계산 실패 시 STANDARD로 진행
            "priority": 0,
            "isDefault": True,
        },
    ],

    # === Persona 2 (lipoCustomer): 흡입 단독 vs 흡입+이식 분기 ===
    # p2InformSurgery에서 upsellAccept 기반 분기
    "p2InformSurgery": [
        {
            "transitionId": "lipoOnly",
            "ruleId": None,  # condLipoOnly (upsellAccept = false)
            "conditionVar": "upsellAccept",
            "conditionOp": "=",
            "conditionRef": "false",
            "targetStepId": "p2InformInfoA",  # 흡입 단독
            "priority": 20,
            "isDefault": False,
        },
        {
            "transitionId": "lipoPlusTransfer",
            "ruleId": None,  # condLipoPlusTransfer (upsellAccept = true)
            "conditionVar": "upsellAccept",
            "conditionOp": "=",
            "conditionRef": "true",
            "targetStepId": "p2InformInfoB",  # 흡입+이식
            "priority": 10,
            "isDefault": False,
        },
        {
            "transitionId": "lipoDefault",
            "ruleId": None,
            "targetStepId": "p2InformInfoA",  # 기본: 흡입 단독 경로
            "priority": 0,
            "isDefault": True,
        },
    ],

    # === Persona 2 (lipoCustomer): 일반 vs 줄기세포 분기 (p2InformInfoB 이후) ===
    "p2InformInfoB": [
        {
            "transitionId": "chooseGeneral",
            "ruleId": None,
            "conditionVar": "transferType",
            "conditionOp": "=",
            "conditionRef": "일반",
            "targetStepId": "p2Finalize",
            "priority": 10,
            "isDefault": False,
        },
        {
            "transitionId": "chooseStemCell",
            "ruleId": None,
            "conditionVar": "transferType",
            "conditionOp": "=",
            "conditionRef": "줄기세포",
            "targetStepId": "p2Finalize",
            "priority": 20,
            "isDefault": False,
        },
        {
            "transitionId": "chooseDefaultUndecided",
            "ruleId": None,
            "targetStepId": "p2Finalize",
            "priority": 0,
            "isDefault": True,
        },
    ],

    # === Persona 4 (longDistance): 거주지 기반 프로토콜 분기 ===
    # p4PreCollect에서 residenceCountry / regionBucket 기반 분기
    "p4PreCollect": [
        {
            "transitionId": "regionPathAbroad",
            "ruleId": "ruleRegionRemote",
            "targetStepId": "p4Collect",  # FULL 프로토콜 (해외)
            "priority": 20,
            "isDefault": False,
        },
        {
            "transitionId": "regionPathSemiRemote",
            "ruleId": "ruleRegionSemiRemote",
            "targetStepId": "p4Collect",  # SEMI-REMOTE 프로토콜 (국내 원거리)
            "priority": 10,
            "isDefault": False,
        },
        {
            "transitionId": "regionPathStandard",
            "ruleId": None,
            "targetStepId": "p4Collect",  # STANDARD 프로토콜 (수도권)
            "priority": 0,
            "isDefault": True,
        },
    ],

    # === Persona 5 (revisionFatigue): 유방암 + 보형물 분기 ===
    # p5AskMedical에서 유방암/보형물 조건 기반 분기 (p5AskDetail에서 분리됨)
    "p5AskMedical": [
        {
            "transitionId": "transCancerCheck",
            "ruleId": "ruleCancerNone",
            "targetStepId": "p5InformSurgery",  # STANDARD
            "priority": 30,
            "isDefault": False,
        },
        {
            "transitionId": "transCancerCheck",
            "ruleId": "ruleCancerConditional",
            "targetStepId": "p5InformSurgery",  # CONDITIONAL
            "priority": 20,
            "isDefault": False,
        },
        {
            "transitionId": "transCancerCheck",
            "ruleId": "ruleCancerNotAllowed",
            "targetStepId": "p5InformSurgery",  # NOT_ALLOWED
            "priority": 10,
            "isDefault": False,
        },
        {
            "transitionId": "transCancerDefault",
            "ruleId": None,
            "targetStepId": "p5InformSurgery",  # Default: 조건 미충족 시 STANDARD로 진행
            "priority": 0,
            "isDefault": True,
        },
    ],
}

# Transition별 관련 Condition ID 매핑 (레거시 fallback)
# CONSIDERS 관계가 있는 DB에서는 CONSIDERS가 우선 사용됨.
# CONSIDERS가 없는 DB (d371fecd 등)에서 fallback으로 사용.
RULE_CONDITION_MAP = {
    "ruleBodyFatHigh": ["condBmiStandard"],
    "ruleBodyFatLow": ["condBmiLowFat"],
    "ruleStandardGuide": ["condProtoclStandard"],
    "ruleLowFatGuideA": ["condProtoclLowFat", "condWeightGainIntent"],
    "ruleLowFatGuideB": ["condProtoclLowFat", "condWeightGainIntentNone"],
    "ruleRegionSemiRemote": ["condRegionSemiRemoteA", "condRegionSemiRemoteB"],
    "ruleRegionRemote": ["condRegionRemote"],
    "ruleInbodyPhotoUpload": ["condInbodyAvailable"],
    "ruleCancerNone": ["condBreastCancerNone"],
    "ruleCancerConditional": ["condBreastCancerHistory", "condCancerSurgeryTypePartial"],
    "ruleCancerNotAllowed": ["condBreastCancerHistory", "condCancerSurgeryTypeTotal"],
    "ruleImplantNone": ["condImplantNone"],
    "ruleImplantIntact": ["condImplantPresence", "condImplantConditionIntact"],
    "ruleImplantDamaged": ["condImplantPresence", "condImplantConditionDamaged"],
}

# OR 로직을 사용하는 DecisionRule (기본값은 AND)
# CONSIDERS에는 AND/OR 의미가 없으므로 별도 지정
OR_LOGIC_RULES = {
    "ruleRegionStandard",  # condRegionSeoul OR condRegionGyeonggi
}

# Guide 선택을 위한 protocolMode/조건 매핑
# Step에 여러 Guide가 연결된 경우, 현재 상태에 따라 적절한 Guide 선택
GUIDE_SELECTION_RULES = {
    # Persona 1: protocolMode 기반 Guide 선택
    "p1InformSurgery": {
        "conditionVar": "protocolMode",
        "mapping": {
            "STANDARD": ["guideStandard"],
            "LOW-FAT": ["guideLowFat"],
        },
    },
    # Persona 4: protocolMode 기반 Guide 선택 (여러 Step에 적용)
    "p4PreCollect": {
        "conditionVar": "protocolMode",
        "mapping": {
            "STANDARD": ["guideStandardPremise"],
            "SEMI-REMOTE": ["guideSemiremotePremise"],
            "FULL": ["guideAbroadPremise"],
        },
    },
    "p4Collect": {
        "conditionVar": "protocolMode",
        "mapping": {
            "STANDARD": ["guideStandardInbody"],
            "SEMI-REMOTE": ["guideSemiremoteInbody"],
            "FULL": ["guideAbroadInbody"],
        },
    },
    "p4AskLifestyle": {
        "conditionVar": "protocolMode",
        "mapping": {
            "STANDARD": ["guideStandardRecovery"],
            "SEMI-REMOTE": ["guideSemiremoteLogic"],
            "FULL": ["guideAbroadLogic"],
        },
    },
    "p4AskDetail": {
        "conditionVar": "protocolMode",
        "mapping": {
            "SEMI-REMOTE": ["guideSemiremoteProcess"],
            "FULL": ["guideAbroadProcess"],
        },
    },
    "p4InformSurgery": {
        "conditionVar": "protocolMode",
        "mapping": {
            "STANDARD": ["guideStandardProcess"],
            "SEMI-REMOTE": ["guideSemiremoteRoute"],
            "FULL": ["guideAbroadProtocol"],
        },
    },
    "p4InformInfo": {
        "conditionVar": "protocolMode",
        "mapping": {
            "STANDARD": ["guideStandardUpload"],
            "SEMI-REMOTE": ["guideSemiremoteUpload"],
            "FULL": ["guideAbroadUpload"],
        },
    },
    "p4Confirm": {
        "conditionVar": "protocolMode",
        "mapping": {
            "STANDARD": ["guideStandardBooking"],
            "SEMI-REMOTE": ["guideSemiremoteBooking"],
            "FULL": ["guideAbroadBooking"],
        },
    },
    "p4Finalize": {
        "conditionVar": "protocolMode",
        "mapping": {
            "STANDARD": ["guideStandardPostCare"],
            "SEMI-REMOTE": ["guideSemiremotePostCare"],
            "FULL": ["guideAbroadPostCare"],
        },
    },
}

# =============================================================================
# 자동 계산 / 조건부 스킵 규칙
# =============================================================================

# 다른 Slot 값으로부터 자동 계산 가능한 항목
# format: { "계산될_slot": { "requires": [필요한 slot들], "compute": "계산_함수_이름" } }
AUTO_COMPUTABLE_SLOTS = {
    # BMI = 체중(kg) / 키(m)^2  →  bodyInfo에서 키/체중 추출 후 계산
    "bmi": {
        "requires": ["bodyInfo"],
        "compute": "compute_bmi",
        "description": "키/체중 → BMI 자동 계산",
    },
    # regionBucket: 해외면 ABROAD, 국내면 지역구 → S1~S6 매핑
    # requires는 최소한 residenceCountry만 있으면 시도 가능 (ABROAD 판별)
    "regionBucket": {
        "requires": ["residenceCountry"],
        "compute": "compute_region_bucket",
        "description": "거주국/국내지역 → 권역(S1~S6/ABROAD) 자동 매핑",
    },
}

# 선행 Slot 값에 따라 질문을 건너뛸 수 있는 항목
# format: { "스킵될_slot": { "when": { "선행_slot": "조건값" }, "action": "skip" } }
# when의 조건이 모두 만족하면 해당 slot을 스킵 (물어보지 않음)
CONDITIONAL_SKIP_RULES = {
    # NOTE: cancerSurgeryType은 breastCancerHistory=false여도 스킵하지 않음.
    #       유방암 외 다른 암 수술 이력이 있을 수 있으므로 항상 확인.

    # 보형물 없으면 보형물 상태/원래 병원 물을 필요 없음
    "implantCondition": {
        "when": {"implantPresence": "false"},
        "action": "skip",
        "default_value": None,
        "description": "보형물 없으면 보형물 상태 불필요",
    },
    "implantOriginHospital": {
        "when": {"implantPresence": "false"},
        "action": "skip",
        "default_value": None,
        "description": "보형물 없으면 원래 병원 불필요",
    },
    # 해외 거주자에겐 국내 지역구 불필요
    "domesticDistrict": {
        "when": {"residenceCountry": "ABROAD"},
        "action": "skip",
        "default_value": None,
        "description": "해외 거주시 국내 지역구 불필요",
    },
    # 체중 증량 의사 없으면 증량 계획/영양 상담 불필요
    "weightGainPlan": {
        "when": {"weightGainIntent": "false"},
        "action": "skip",
        "default_value": None,
        "description": "체중 증량 의사 없으면 증량 계획 불필요",
    },
    "nutritionConsult": {
        "when": {"weightGainIntent": "false"},
        "action": "skip",
        "default_value": None,
        "description": "체중 증량 의사 없으면 영양 상담 불필요",
    },
    # InBody 데이터 없으면 사진 업로드 요청 불필요
    "inbodyPhotoUpload": {
        "when": {"inbodyAvailable": "false"},
        "action": "skip",
        "default_value": None,
        "description": "InBody 없으면 사진 업로드 불필요",
    },
    # 과거 시술 없으면 시술 부위 물을 필요 없음
    "pastOpsSite": {
        "when": {"pastOps": ["없음", "없습니다", "false", "none", "no", "처음"]},
        "action": "skip",
        "default_value": None,
        "description": "과거 시술 없으면 시술 부위 불필요",
    },
}

# 시스템이 자동 설정하는 Slot (절대 사용자에게 물어보면 안 됨)
SYSTEM_MANAGED_SLOTS = [
    "protocolMode",  # 분기 규칙에 의해 자동 설정
]

# CheckItem 힌트: 추출/응답 프롬프트에서 변수의 의미를 명확히 전달
CHECKITEM_HINTS = {
    # === 공통 신체정보 ===
    "bodyInfo": "키(cm)와 체중(kg)을 함께 기재. 예: '170cm 65kg'",
    "bodyFat": "체지방률(%). 예: '25%'",
    "bodyType": "체형 분류: 마른편 / 보통 / 비만형",
    "inbodyAvailable": "인바디 검사 결과 보유 여부. true 또는 false",
    "inbodyPhotoUpload": "인바디 결과 사진 업로드 여부. true 또는 false",

    # === 공통 시술 이력 ===
    "fatSourceAvailability": "지방 채취 가능 부위 및 지방량. 예: '복부 충분', '허벅지 소량'",
    "pastOps": "과거 수술/시술 이력. 예: '가슴 확대 1회', '가슴 보형물 삽입 1회', '없음'",
    "pastOpsSite": "과거 수술 부위. 예: '가슴', '가슴 좌측', '가슴 양측'",
    "smoking": "흡연 여부. true 또는 false",

    # === P1 슬림바디 ===
    "activityPattern": "일상 활동 패턴. 예: '사무직', '활동적', '운동 자주'",
    "exerciseLevel": "운동 빈도/강도. 예: '주 3회', '거의 안 함'",
    "dietPattern": "식습관/식이 패턴. 예: '저탄고지', '불규칙'",
    "weightGainIntent": "체중 증량 의사. true 또는 false",
    "weightGainPlan": "체중 증량 구체 계획",
    "nutritionConsult": "영양 상담 희망 여부. true 또는 false",
    "concernArea": "관심/고민 부위. 예: '가슴', '가슴 볼륨', '가슴 탄력'",
    "surgeryWindow": "희망 시술 시기. 예: '다음 달', '3개월 내'",
    "recheckSchedule": "재진 일정. 예: '2주 후'",
    "recoveryGuideline": "회복 가이드라인/주의사항. 예: '2주간 압박복 착용', '음주 금지'",

    # === P2 지방흡입 ===
    "basicInfo": "고객 이름과 연락처. 예: '김지현 010-1234-5678'",
    "schedule": "방문 가능 일정",
    "medicalHistory": "과거 병력/수술 이력",
    "upsellAccept": "지방이식 추가 시술 동의. true 또는 false",
    "transferType": "이식 유형 선택: 일반 또는 줄기세포",
    "transferPlanDetail": "이식 세부 계획. 예: '줄기세포 이식 + 가슴 볼륨 보충', '일반 이식 + 가슴 볼륨업'",
    "recoveryAllowance": "회복 가능 기간. 예: '1주일', '2주'",
    "travelConstraint": "이동/방문 제약사항",
    "precheckRequired": "사전검사 필요 여부. true 또는 false",
    "visitSchedule": "방문 예약 일정",
    "sameDayPossible": "당일 시술 가능 여부. true 또는 false",
    "reservationIntent": "예약 의사. true 또는 false",
    "depositReservation": "예약금 결제 의사. true 또는 false",
    "jobIntensity": "직업 강도/활동 수준. 예: '사무직(낮음)', '현장직(높음)', '서비스직(보통)'",
    "lipoArea": "지방흡입 희망 부위 (가슴 이식용 채취). 예: '복부', '허벅지', '옆구리'",
    "lipoGoal": "지방흡입 목표/기대 결과. 예: '가슴 볼륨업', '가슴 지방이식용 채취'",
    "lipoPlanDetail": "흡입 세부 계획. 예: '복부+허벅지 동시 흡입 후 가슴 이식'",
    "riskFactor": "위험 요소/우려사항. 예: '고혈압', '당뇨', '없음'",
    "planPreference": "시술 계획 선호. 예: '한 번에 진행', '단계별 진행'",
    "concernSideEffect": "우려하는 부작용. 예: '울퉁불퉁', '비대칭', '감각 이상'",
    "costSensitivity": "비용 민감도. 예: '예산 중요', '결과 우선', '적절한 선에서'",
    "recoveryTimeline": "회복 일정/기간. 예: '1주 후 출근', '2주 재택'",
    "costRange": "예산 범위. 예: '300만원 이내', '500만원 이내', '제한 없음'",
    "graftExpectation": "이식 기대 효과. 예: '자연스러운 가슴 볼륨', '가슴 탄력 개선'",

    # === P3 피부시술 ===
    "skinType": "피부 타입. 예: '건성', '지성', '복합성', '민감성'",
    "skinCondition": "현재 피부 상태. 예: '가슴 부위 탄력 저하', '수술 후 흉터', '색소침착'",
    "allergyHistory": "알레르기 이력",
    "botoxCycle": "보톡스 시술 주기. 예: '6개월마다', '처음'",
    "fillerHistory": "필러 시술 이력",
    "fillerRemaining": "기존 필러 잔여량/상태. 예: '거의 흡수됨', '일부 남아있음', '없음'",
    "procedurePlan": "시술 계획/선호 시술. 예: '가슴성형 전후 피부관리', '수술 후 피부 탄력 관리'",
    "sunExposure": "자외선 노출 정도. 예: '야외 활동 많음', '실내 위주', '자외선 차단 꾸준히'",
    "skincareRoutine": "스킨케어 루틴. 예: '기초만', '풀코스', '거의 안 함'",
    "desiredEffect": "희망 효과. 예: '가슴 피부 탄력', '수술 후 피부 회복', '흉터 최소화'",
    "durabilityExpectation": "효과 지속 기간 기대. 예: '6개월 이상', '1년', '반영구'",

    # === P4 원거리 ===
    "residenceCountry": "거주국. 예: '한국', '미국', '일본' 또는 '해외'",
    "domesticDistrict": "국내 거주 지역. 예: '서울', '부산', '경기'",
    "regionBucket": "지역 분류 코드 (자동 계산). S1(서울)~S6(강원/제주)",
    "visitPeriod": "한국 방문/체류 기간",
    "aftercarePlan": "시술 후 관리 계획",
    "followupSchedule": "사후 관리 일정",
    "precheckTimeEstimate": "사전검사 소요 시간 예상. 예: '30분', '1시간'",
    "bodyPhotoUpload": "체형 사진 업로드 여부. true 또는 false",
    "documentUpload": "서류(의료기록 등) 업로드 여부. true 또는 false",

    # === P5 재수술 ===
    "breastCancerHistory": "유방암 병력. true 또는 false",
    "cancerSurgeryType": "암 수술 유형: 부분절제 또는 전절제",
    "implantPresence": "보형물 삽입 여부. true 또는 false",
    "implantCondition": "보형물 상태. 예: '양호', '파손', '구축'",
    "implantOriginHospital": "보형물 시술 병원명",
    "revisionReason": "재수술 사유",
    "priorSurgeryCount": "이전 수술 횟수. 예: '1회', '2회'",
    "workConstraint": "직업 제약사항. 예: '2주 후 출근 필수', '재택 가능', '육체 노동'",
    "scarManagement": "흉터 관리 방법. 예: '실리콘 시트', '레이저', '자연 치유'",
    "riskExplanationLevel": "위험성 설명 수준. 예: '상세히', '핵심만', '서면으로'",

    # === 개인정보 (공통 마무리 단계) ===
    "customerName": "고객 성함",
    "phoneNumber": "연락처 (휴대폰 번호). 예: '010-1234-5678'",

    # === 시스템 관리 (참조용) ===
    "protocolMode": "시술 프로토콜 모드 (분기 규칙에 의해 자동 설정)",
}

# 국내 지역구 → regionBucket 매핑 테이블
REGION_BUCKET_MAP = {
    # S1: 서울
    "서울": "S1",
    # S2: 경기
    "경기": "S2", "인천": "S2",
    # S3: 충청/대전/세종
    "대전": "S3", "세종": "S3", "충남": "S3", "충북": "S3", "충청": "S3",
    # S4: 영남/부산/대구/울산
    "부산": "S4", "대구": "S4", "울산": "S4", "경남": "S4", "경북": "S4",
    # S5: 호남/광주/전라
    "광주": "S5", "전남": "S5", "전북": "S5", "전라": "S5",
    # S6: 강원/제주
    "강원": "S6", "제주": "S6",
}


# =============================================================================
# 유틸리티 함수
# =============================================================================

def extract_local_id(uri: str) -> str:
    """URI에서 로컬 ID 추출 (# 또는 / 뒤의 부분)"""
    if "#" in uri:
        return uri.split("#")[-1]
    return uri.split("/")[-1]


