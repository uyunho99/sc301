#!/bin/bash
# Neo4j Cypher import 스크립트
# 서버에서 실행: bash scripts/import_neo4j.sh

set -e

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
CYPHER_FILE="$PROJECT_DIR/backups/neo4j_export.cypher"

# .env에서 Neo4j 로컬 접속 정보 읽기
if [ -f "$PROJECT_DIR/.env" ]; then
    NEO4J_URI=$(grep NEO4J_LOCAL_URI "$PROJECT_DIR/.env" | cut -d= -f2)
    NEO4J_USER=$(grep NEO4J_LOCAL_USER "$PROJECT_DIR/.env" | cut -d= -f2)
    NEO4J_PASS=$(grep NEO4J_LOCAL_PASSWORD "$PROJECT_DIR/.env" | cut -d= -f2)
fi

NEO4J_URI=${NEO4J_URI:-"bolt://localhost:7687"}
NEO4J_USER=${NEO4J_USER:-"neo4j"}
NEO4J_PASS=${NEO4J_PASS:-"password"}

echo "========================================="
echo "  Neo4j 데이터 Import"
echo "========================================="
echo "소스: $CYPHER_FILE"
echo "대상: $NEO4J_URI"
echo ""

if [ ! -f "$CYPHER_FILE" ]; then
    echo "❌ $CYPHER_FILE 파일이 없습니다."
    exit 1
fi

# Neo4j 실행 확인
if ! sudo systemctl is-active --quiet neo4j; then
    echo "Neo4j 시작 중..."
    sudo systemctl start neo4j
    sleep 5
fi

# 기존 데이터 삭제 확인
echo "⚠ 기존 데이터를 모두 삭제하고 import 합니다."
read -p "계속하시겠습니까? (y/N): " confirm
if [ "$confirm" != "y" ] && [ "$confirm" != "Y" ]; then
    echo "취소됨."
    exit 0
fi

echo ""
echo "[1/2] 기존 데이터 삭제..."
cypher-shell -u "$NEO4J_USER" -p "$NEO4J_PASS" -a "$NEO4J_URI" \
    "MATCH (n) DETACH DELETE n;"

echo "[2/2] Cypher import 실행..."
cypher-shell -u "$NEO4J_USER" -p "$NEO4J_PASS" -a "$NEO4J_URI" \
    --file "$CYPHER_FILE"

echo ""
echo "========================================="
echo "  ✅ Import 완료!"
echo "========================================="

# 결과 확인
echo ""
echo "데이터 확인:"
cypher-shell -u "$NEO4J_USER" -p "$NEO4J_PASS" -a "$NEO4J_URI" \
    "MATCH (n) RETURN labels(n)[0] AS label, count(n) AS count ORDER BY count DESC;"
