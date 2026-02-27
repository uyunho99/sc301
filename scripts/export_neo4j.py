"""
Neo4j 데이터 → Cypher 내보내기 스크립트
로컬에서 실행: python scripts/export_neo4j.py

Block format (Enterprise) → Cypher 텍스트 → Community에서 import 가능
"""

import json
import os
from neo4j import GraphDatabase

# 로컬 Neo4j 접속 정보
URI = os.getenv("NEO4J_LOCAL_URI", "bolt://localhost:7687")
USER = os.getenv("NEO4J_LOCAL_USER", "neo4j")
PASSWORD = os.getenv("NEO4J_LOCAL_PASSWORD", "password")

OUTPUT_FILE = os.path.join(os.path.dirname(__file__), "..", "backups", "neo4j_export.cypher")


def export_database():
    driver = GraphDatabase.driver(URI, auth=(USER, PASSWORD))

    with driver.session() as session:
        lines = []

        # ─── 1. 모든 Constraints 내보내기 ───
        print("[1/4] Constraints 내보내기...")
        constraints = session.run("SHOW CONSTRAINTS").data()
        for c in constraints:
            if c.get("createStatement"):
                lines.append(c["createStatement"] + ";")
        if constraints:
            lines.append("")

        # ─── 2. 모든 Indexes 내보내기 ───
        print("[2/4] Indexes 내보내기...")
        indexes = session.run("SHOW INDEXES").data()
        for idx in indexes:
            # constraint가 만든 index는 건너뛰기
            if idx.get("owningConstraint"):
                continue
            if idx.get("createStatement"):
                lines.append(idx["createStatement"] + ";")
        if indexes:
            lines.append("")

        # ─── 3. 모든 노드 내보내기 ───
        print("[3/4] 노드 내보내기...")
        nodes = session.run(
            "MATCH (n) RETURN elementId(n) AS eid, labels(n) AS labels, properties(n) AS props"
        ).data()

        node_id_map = {}  # elementId -> varName
        for i, node in enumerate(nodes):
            var = f"n{i}"
            node_id_map[node["eid"]] = var
            labels_str = ":" + ":".join(node["labels"]) if node["labels"] else ""
            # embedding 프로퍼티 제외 (복원 후 _create_embeddings()로 새로 생성)
            props = {k: v for k, v in node["props"].items() if k != "embedding"}
            props_str = serialize_props(props)
            lines.append(f"CREATE ({var}{labels_str} {props_str});")

        print(f"  노드 {len(nodes)}개")
        lines.append("")

        # ─── 4. 모든 관계 내보내기 ───
        # cypher-shell은 문(statement) 단위로 실행하므로 변수 참조가 불가.
        # 노드 index(순서) → 고유 식별 MATCH 문으로 관계를 생성한다.
        print("[4/4] 관계 내보내기...")

        # elementId → (labels, 고유 식별 프로퍼티) 매핑 구축
        node_match_map = {}  # elementId -> MATCH 패턴 문자열
        for node in nodes:
            eid = node["eid"]
            labels = node["labels"]
            props = node["props"]
            label_str = ":" + ":".join(labels) if labels else ""

            # 고유 식별자 결정: id > uri > 전체 프로퍼티
            if "id" in props:
                match_props = serialize_props({"id": props["id"]})
            elif "uri" in props:
                match_props = serialize_props({"uri": props["uri"]})
            else:
                # _GraphConfig, _NsPrefDef 등 id/uri 없는 노드
                match_key = next(iter(props), None)
                if match_key:
                    match_props = serialize_props({match_key: props[match_key]})
                else:
                    match_props = "{}"
            node_match_map[eid] = f"(n{label_str} {match_props})"

        rels = session.run("""
            MATCH (a)-[r]->(b)
            RETURN elementId(a) AS src, elementId(b) AS dst,
                   type(r) AS type, properties(r) AS props
        """).data()

        for rel in rels:
            src_match = node_match_map.get(rel["src"])
            dst_match = node_match_map.get(rel["dst"])
            if not src_match or not dst_match:
                continue
            props_str = serialize_props(rel["props"])
            src_pat = src_match.replace("(n", "(a")
            dst_pat = dst_match.replace("(n", "(b")
            if props_str != "{}":
                lines.append(f"MATCH {src_pat}, {dst_pat} CREATE (a)-[:{rel['type']} {props_str}]->(b);")
            else:
                lines.append(f"MATCH {src_pat}, {dst_pat} CREATE (a)-[:{rel['type']}]->(b);")

        print(f"  관계 {len(rels)}개")

    driver.close()

    # 파일로 저장
    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write("// SC301 Neo4j 데이터 export\n")
        f.write("// 생성: scripts/export_neo4j.py\n")
        f.write("// 복원: scripts/import_neo4j.sh (서버에서 실행)\n\n")
        f.write("\n".join(lines))

    size_kb = os.path.getsize(OUTPUT_FILE) / 1024
    print(f"\n✅ 내보내기 완료: {OUTPUT_FILE} ({size_kb:.1f}KB)")
    print(f"   노드: {len(nodes)}개, 관계: {len(rels)}개")


def serialize_props(props: dict) -> str:
    """Neo4j 속성을 Cypher 리터럴로 변환"""
    if not props:
        return "{}"
    pairs = []
    for k, v in props.items():
        pairs.append(f"{k}: {cypher_literal(v)}")
    return "{" + ", ".join(pairs) + "}"


def cypher_literal(value) -> str:
    """Python 값을 Cypher 리터럴 문자열로 변환"""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        escaped = value.replace("\\", "\\\\").replace("'", "\\'").replace("\n", "\\n").replace("\r", "\\r")
        return f"'{escaped}'"
    if isinstance(value, list):
        items = ", ".join(cypher_literal(item) for item in value)
        return f"[{items}]"
    if isinstance(value, dict):
        pairs = ", ".join(f"{k}: {cypher_literal(v)}" for k, v in value.items())
        return "{" + pairs + "}"
    # fallback
    return f"'{value}'"


if __name__ == "__main__":
    export_database()
