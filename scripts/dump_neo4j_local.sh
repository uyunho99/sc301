#!/bin/bash
# Neo4j Desktop → .dump 파일 생성 (로컬 맥에서 실행)
# ⚠ Neo4j Desktop에서 DB를 먼저 Stop 한 뒤 실행!
# 사용법: bash scripts/dump_neo4j_local.sh

set -e

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
BACKUP_DIR="$PROJECT_DIR/backups"

# Neo4j Desktop DBMS 경로
NEO4J_HOME="/Users/yunho/Library/Application Support/neo4j-desktop/Application/Data/dbmss/dbms-d371fecd-79a9-4d0a-aa35-1c1eabc21158"
NEO4J_ADMIN="$NEO4J_HOME/bin/neo4j-admin"
DB_NAME="neo4j"

echo "========================================="
echo "  Neo4j Desktop → Dump 생성"
echo "========================================="

# neo4j-admin 확인
if [ ! -f "$NEO4J_ADMIN" ]; then
    echo "❌ neo4j-admin을 찾을 수 없습니다: $NEO4J_ADMIN"
    exit 1
fi

echo ""
echo "⚠ Neo4j Desktop에서 DB를 먼저 Stop 하세요!"
echo "   (Desktop → DB 카드 → Stop 클릭)"
echo ""
read -p "DB가 중지되었나요? (y/N): " confirm
if [ "$confirm" != "y" ] && [ "$confirm" != "Y" ]; then
    echo "취소됨."
    exit 0
fi

mkdir -p "$BACKUP_DIR"

# 기존 dump 파일 백업
if [ -f "$BACKUP_DIR/${DB_NAME}.dump" ]; then
    OLD_DATE=$(date -r "$BACKUP_DIR/${DB_NAME}.dump" +%y%m%d)
    echo "기존 dump → neo4j-${OLD_DATE}.dump.bak 으로 백업"
    mv "$BACKUP_DIR/${DB_NAME}.dump" "$BACKUP_DIR/neo4j-${OLD_DATE}.dump.bak"
fi

echo ""
echo "Dump 생성 중..."
"$NEO4J_ADMIN" database dump "$DB_NAME" \
    --to-path="$BACKUP_DIR" \
    --overwrite-destination=true

if [ -f "$BACKUP_DIR/${DB_NAME}.dump" ]; then
    SIZE=$(du -h "$BACKUP_DIR/${DB_NAME}.dump" | cut -f1)
    echo ""
    echo "========================================="
    echo "  ✅ Dump 생성 완료!"
    echo "========================================="
    echo "  파일: backups/${DB_NAME}.dump"
    echo "  크기: $SIZE"
    echo ""
    echo "  Git push:"
    echo "    git add backups/${DB_NAME}.dump"
    echo "    git commit -m 'update neo4j dump'"
    echo "    git push"
    echo ""
    echo "  서버 복원:"
    echo "    bash scripts/restore_neo4j.sh"
else
    echo "❌ Dump 파일이 생성되지 않았습니다."
    echo "backups/ 내용:"
    ls -la "$BACKUP_DIR/"
    exit 1
fi
