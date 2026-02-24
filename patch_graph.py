"""
patch_graph.py - Neo4j 그래프 패치 스크립트

수정 사항:
1. #3: P1, P3, P4, P5의 마무리 스텝에 개인정보 CheckItem 추가
   (customerName, phoneNumber)
2. #9: p5AskDetail의 CheckItem 과밀 분리
   → p5AskDetail(유방암/보형물 관련) + p5AskMedical(기타 의료정보) 분리
3. CONSIDERS 관계 보완: 누락된 DecisionRule → Condition 매핑 추가

사용법:
  python patch_graph.py --db local     # 로컬 Neo4j
  python patch_graph.py --db aura      # AuraDB
  python patch_graph.py --db local --dry-run  # 실행 없이 쿼리만 출력
"""
import argparse
import os
from dotenv import load_dotenv
from neo4j import GraphDatabase

load_dotenv()


# =============================================================================
# 1. 개인정보 CheckItem 노드 생성 + 마무리 스텝에 연결
# =============================================================================

PATCH_PERSONAL_INFO = [
    # CheckItem 노드 생성 (MERGE: 이미 있으면 스킵)
    """
    MERGE (ci:CheckItem {id: 'customerName'})
    SET ci.name = '고객 성함', ci.dataType = 'string'
    """,
    """
    MERGE (ci:CheckItem {id: 'phoneNumber'})
    SET ci.name = '연락처', ci.dataType = 'string'
    """,

    # P1 Confirm 스텝에 연결
    """
    MATCH (st:Step {id: 'p1Confirm'}), (ci:CheckItem {id: 'customerName'})
    MERGE (st)-[:CHECKS]->(ci)
    """,
    """
    MATCH (st:Step {id: 'p1Confirm'}), (ci:CheckItem {id: 'phoneNumber'})
    MERGE (st)-[:CHECKS]->(ci)
    """,

    # P3 Confirm 스텝에 연결
    """
    MATCH (st:Step {id: 'p3Confirm'}), (ci:CheckItem {id: 'customerName'})
    MERGE (st)-[:CHECKS]->(ci)
    """,
    """
    MATCH (st:Step {id: 'p3Confirm'}), (ci:CheckItem {id: 'phoneNumber'})
    MERGE (st)-[:CHECKS]->(ci)
    """,

    # P4 Finalize 스텝에 연결
    """
    MATCH (st:Step {id: 'p4Finalize'}), (ci:CheckItem {id: 'customerName'})
    MERGE (st)-[:CHECKS]->(ci)
    """,
    """
    MATCH (st:Step {id: 'p4Finalize'}), (ci:CheckItem {id: 'phoneNumber'})
    MERGE (st)-[:CHECKS]->(ci)
    """,

    # P5 Confirm 스텝에 연결
    """
    MATCH (st:Step {id: 'p5Confirm'}), (ci:CheckItem {id: 'customerName'})
    MERGE (st)-[:CHECKS]->(ci)
    """,
    """
    MATCH (st:Step {id: 'p5Confirm'}), (ci:CheckItem {id: 'phoneNumber'})
    MERGE (st)-[:CHECKS]->(ci)
    """,
]


# =============================================================================
# 2. p5AskDetail 분리: 핵심 분기 항목만 남기고 나머지는 p5AskMedical로 이동
#
# 현재 p5AskDetail에 있는 CheckItem (예상):
#   - breastCancerHistory (분기용 - 유지)
#   - cancerSurgeryType (분기용 - 유지)
#   - implantPresence (분기용 - 유지)
#   - implantCondition (조건부 - p5AskMedical로 이동)
#   - implantOriginHospital (조건부 - p5AskMedical로 이동)
#   - revisionReason (p5AskMedical로 이동)
#   - priorSurgeryCount (p5AskMedical로 이동)
#
# 새 흐름: p5AskDetail → p5AskMedical → (분기) → p5InformSurgery
# =============================================================================

PATCH_P5_SPLIT = [
    # 1. p5AskMedical 스텝 생성
    """
    MERGE (st:Step {id: 'p5AskMedical'})
    SET st.name = '추가 의료정보 확인',
        st.desc = '보형물 상태, 재수술 사유, 이전 수술 이력 등 추가 정보 확인',
        st.type = 'ask'
    """,

    # 2. p5AskMedical을 시나리오에 연결
    """
    MATCH (sc:Scenario)-[:HAS_STEP]->(st:Step {id: 'p5AskDetail'})
    MATCH (newSt:Step {id: 'p5AskMedical'})
    MERGE (sc)-[:HAS_STEP]->(newSt)
    """,

    # 3. 비분기 CheckItem을 p5AskMedical로 이동
    #    (CHECKS 관계를 p5AskDetail에서 제거하고 p5AskMedical에 추가)

    # implantCondition: p5AskDetail → p5AskMedical
    """
    MATCH (old:Step {id: 'p5AskDetail'})-[r:CHECKS]->(ci:CheckItem {id: 'implantCondition'})
    DELETE r
    WITH ci
    MATCH (newSt:Step {id: 'p5AskMedical'})
    MERGE (newSt)-[:CHECKS]->(ci)
    """,

    # implantOriginHospital: p5AskDetail → p5AskMedical
    """
    MATCH (old:Step {id: 'p5AskDetail'})-[r:CHECKS]->(ci:CheckItem {id: 'implantOriginHospital'})
    DELETE r
    WITH ci
    MATCH (newSt:Step {id: 'p5AskMedical'})
    MERGE (newSt)-[:CHECKS]->(ci)
    """,

    # revisionReason: p5AskDetail → p5AskMedical
    """
    MATCH (old:Step {id: 'p5AskDetail'})-[r:CHECKS]->(ci:CheckItem {id: 'revisionReason'})
    DELETE r
    WITH ci
    MATCH (newSt:Step {id: 'p5AskMedical'})
    MERGE (newSt)-[:CHECKS]->(ci)
    """,

    # priorSurgeryCount: p5AskDetail → p5AskMedical
    """
    MATCH (old:Step {id: 'p5AskDetail'})-[r:CHECKS]->(ci:CheckItem {id: 'priorSurgeryCount'})
    DELETE r
    WITH ci
    MATCH (newSt:Step {id: 'p5AskMedical'})
    MERGE (newSt)-[:CHECKS]->(ci)
    """,

    # 4. 흐름 재연결: p5AskDetail → p5AskMedical → (기존 p5AskDetail의 TO 대상)
    #    기존: p5AskDetail -[:TO]-> (분기 대상은 BRANCHING_RULES에서 처리)
    #    새로: p5AskDetail -[:TO]-> p5AskMedical (선형)
    #          p5AskMedical은 분기 스텝 (BRANCHING_RULES에서 처리)

    # 기존 p5AskDetail의 TO 관계 제거
    """
    MATCH (st:Step {id: 'p5AskDetail'})-[r:TO]->(:Step)
    DELETE r
    """,

    # p5AskDetail → p5AskMedical 연결
    """
    MATCH (a:Step {id: 'p5AskDetail'}), (b:Step {id: 'p5AskMedical'})
    MERGE (a)-[:TO]->(b)
    """,

    # p5AskMedical → p5InformSurgery 연결 (분기 목적지)
    """
    MATCH (a:Step {id: 'p5AskMedical'}), (b:Step {id: 'p5InformSurgery'})
    MERGE (a)-[:TO]->(b)
    """,
]


# =============================================================================
# 3. CONSIDERS 관계 보완: 누락된 DecisionRule → Condition 매핑 추가
#
# 66da1696 DB의 CONSIDERS 관계에서 누락된 항목 보완:
#   - ruleCancerConditional: condCancerSurgeryTypePartial 누락
#   - ruleCancerNotAllowed: condCancerSurgeryTypeTotal 누락
#   - ruleImplantIntact: 노드 자체 없음 → 생성 + CONSIDERS 연결
#   - ruleImplantDamaged: 노드 자체 없음 → 생성 + CONSIDERS 연결
# =============================================================================

PATCH_CONSIDERS = [
    # ruleCancerConditional에 condCancerSurgeryTypePartial 추가
    """
    MATCH (r:DecisionRule {id: 'ruleCancerConditional'}),
          (c:Condition {id: 'condCancerSurgeryTypePartial'})
    MERGE (r)-[:CONSIDERS]->(c)
    """,

    # ruleCancerNotAllowed에 condCancerSurgeryTypeTotal 추가
    """
    MATCH (r:DecisionRule {id: 'ruleCancerNotAllowed'}),
          (c:Condition {id: 'condCancerSurgeryTypeTotal'})
    MERGE (r)-[:CONSIDERS]->(c)
    """,

    # ruleImplantIntact 노드 생성 + CONSIDERS 연결
    """
    MERGE (r:DecisionRule {id: 'ruleImplantIntact'})
    SET r.desc = '보형물 있고 상태 양호'
    WITH r
    MATCH (c1:Condition {id: 'condImplantPresence'}),
          (c2:Condition {id: 'condImplantConditionIntact'})
    MERGE (r)-[:CONSIDERS]->(c1)
    MERGE (r)-[:CONSIDERS]->(c2)
    """,

    # ruleImplantDamaged 노드 생성 + CONSIDERS 연결
    """
    MERGE (r:DecisionRule {id: 'ruleImplantDamaged'})
    SET r.desc = '보형물 있고 파손/구축'
    WITH r
    MATCH (c1:Condition {id: 'condImplantPresence'}),
          (c2:Condition {id: 'condImplantConditionDamaged'})
    MERGE (r)-[:CONSIDERS]->(c1)
    MERGE (r)-[:CONSIDERS]->(c2)
    """,
]


def get_driver(db_mode: str):
    if db_mode == "local":
        uri = os.environ.get("NEO4J_LOCAL_URI", "bolt://localhost:7687")
        user = os.environ.get("NEO4J_LOCAL_USER", "neo4j")
        password = os.environ.get("NEO4J_LOCAL_PASSWORD", "password")
        return GraphDatabase.driver(uri, auth=(user, password))
    else:
        uri = os.environ.get("NEO4J_AURA_URI")
        user = os.environ.get("NEO4J_AURA_USER")
        password = os.environ.get("NEO4J_AURA_PASSWORD")
        return GraphDatabase.driver(uri, auth=(user, password))


def run_patches(driver, patches: list[str], label: str, dry_run: bool = False):
    print(f"\n{'='*60}")
    print(f"  {label}")
    print(f"{'='*60}")

    for i, query in enumerate(patches, 1):
        query_preview = query.strip().split('\n')[0][:80]
        if dry_run:
            print(f"  [{i}/{len(patches)}] DRY-RUN: {query_preview}...")
        else:
            try:
                with driver.session() as session:
                    result = session.run(query.strip())
                    summary = result.consume()
                    stats = summary.counters
                    changes = []
                    if stats.nodes_created: changes.append(f"노드 생성: {stats.nodes_created}")
                    if stats.relationships_created: changes.append(f"관계 생성: {stats.relationships_created}")
                    if stats.relationships_deleted: changes.append(f"관계 삭제: {stats.relationships_deleted}")
                    if stats.properties_set: changes.append(f"속성 설정: {stats.properties_set}")
                    change_str = ", ".join(changes) if changes else "변경 없음 (이미 존재)"
                    print(f"  [{i}/{len(patches)}] ✅ {change_str}")
            except Exception as e:
                print(f"  [{i}/{len(patches)}] ❌ 오류: {e}")


def verify_patch(driver):
    """패치 결과 검증"""
    print(f"\n{'='*60}")
    print(f"  패치 결과 검증")
    print(f"{'='*60}")

    checks = [
        ("개인정보 CheckItem 존재",
         "MATCH (ci:CheckItem) WHERE ci.id IN ['customerName', 'phoneNumber'] RETURN ci.id AS id, ci.name AS name"),
        ("P1 Confirm - 개인정보 연결",
         "MATCH (st:Step {id: 'p1Confirm'})-[:CHECKS]->(ci:CheckItem) RETURN ci.id AS id ORDER BY ci.id"),
        ("P3 Confirm - 개인정보 연결",
         "MATCH (st:Step {id: 'p3Confirm'})-[:CHECKS]->(ci:CheckItem) RETURN ci.id AS id ORDER BY ci.id"),
        ("P4 Finalize - 개인정보 연결",
         "MATCH (st:Step {id: 'p4Finalize'})-[:CHECKS]->(ci:CheckItem) RETURN ci.id AS id ORDER BY ci.id"),
        ("P5 Confirm - 개인정보 연결",
         "MATCH (st:Step {id: 'p5Confirm'})-[:CHECKS]->(ci:CheckItem) RETURN ci.id AS id ORDER BY ci.id"),
        ("p5AskDetail CheckItems (분기용만)",
         "MATCH (st:Step {id: 'p5AskDetail'})-[:CHECKS]->(ci:CheckItem) RETURN ci.id AS id ORDER BY ci.id"),
        ("p5AskMedical CheckItems (이동됨)",
         "MATCH (st:Step {id: 'p5AskMedical'})-[:CHECKS]->(ci:CheckItem) RETURN ci.id AS id ORDER BY ci.id"),
        ("p5 흐름: AskDetail → AskMedical → InformSurgery",
         "MATCH (a:Step {id: 'p5AskDetail'})-[:TO]->(b)-[:TO]->(c) RETURN a.id AS step1, b.id AS step2, c.id AS step3"),
        ("CONSIDERS: ruleCancerConditional",
         "MATCH (r:DecisionRule {id: 'ruleCancerConditional'})-[:CONSIDERS]->(c:Condition) RETURN collect(c.id) AS conds"),
        ("CONSIDERS: ruleCancerNotAllowed",
         "MATCH (r:DecisionRule {id: 'ruleCancerNotAllowed'})-[:CONSIDERS]->(c:Condition) RETURN collect(c.id) AS conds"),
        ("CONSIDERS: ruleImplantIntact",
         "MATCH (r:DecisionRule {id: 'ruleImplantIntact'})-[:CONSIDERS]->(c:Condition) RETURN collect(c.id) AS conds"),
        ("CONSIDERS: ruleImplantDamaged",
         "MATCH (r:DecisionRule {id: 'ruleImplantDamaged'})-[:CONSIDERS]->(c:Condition) RETURN collect(c.id) AS conds"),
    ]

    with driver.session() as session:
        for label, query in checks:
            result = session.run(query)
            records = [dict(r) for r in result]
            if records:
                print(f"  ✅ {label}: {records}")
            else:
                print(f"  ⚠️  {label}: 결과 없음")


def main():
    parser = argparse.ArgumentParser(description="Neo4j 그래프 패치")
    parser.add_argument("--db", choices=["local", "aura"], default="local")
    parser.add_argument("--dry-run", action="store_true", help="실행 없이 쿼리만 출력")
    args = parser.parse_args()

    driver = get_driver(args.db)

    try:
        # 연결 확인
        with driver.session() as session:
            result = session.run("RETURN 1")
            result.consume()
        print(f"✅ Neo4j ({args.db}) 연결 성공")

        run_patches(driver, PATCH_PERSONAL_INFO, "#3: 개인정보 CheckItem 추가", args.dry_run)
        run_patches(driver, PATCH_P5_SPLIT, "#9: p5AskDetail → p5AskDetail + p5AskMedical 분리", args.dry_run)
        run_patches(driver, PATCH_CONSIDERS, "CONSIDERS 관계 보완", args.dry_run)

        if not args.dry_run:
            verify_patch(driver)

    finally:
        driver.close()


if __name__ == "__main__":
    main()
