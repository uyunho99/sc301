#!/bin/bash
# Neo4j Desktop → .dump 파일 생성 (로컬 맥에서 실행)
# ⚠ Neo4j Desktop에서 DB를 먼저 Stop 한 뒤 실행!
#
# Desktop(Enterprise)은 block format을 사용하지만
# 서버(Community)는 aligned format만 지원하므로
# copy → aligned 변환 → dump 순서로 처리합니다.
#
# 사용법: bash scripts/dump_neo4j_local.sh

set -e

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
BACKUP_DIR="$PROJECT_DIR/backups"

# Neo4j Desktop DBMS 경로
NEO4J_HOME="/Users/yunho/Library/Application Support/neo4j-desktop/Application/Data/dbmss/dbms-d371fecd-79a9-4d0a-aa35-1c1eabc21158"
NEO4J_ADMIN="$NEO4J_HOME/bin/neo4j-admin"
DB_NAME="neo4j"
TEMP_DB="neo4j-aligned"

echo "========================================="
echo "  Neo4j Desktop → Dump 생성"
echo "  (block → aligned 변환 포함)"
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

# ─────────────────────────────────────
# 1. block → aligned 포맷 변환 (copy)
# ─────────────────────────────────────
echo ""
echo "[1/3] Block → Aligned 포맷 변환..."

# 이전 임시 DB 정리
TEMP_DB_DIR="$NEO4J_HOME/data/databases/$TEMP_DB"
TEMP_TX_DIR="$NEO4J_HOME/data/transactions/$TEMP_DB"
rm -rf "$TEMP_DB_DIR" "$TEMP_TX_DIR" 2>/dev/null || true

"$NEO4J_ADMIN" database copy \
    --to-format=aligned \
    --force \
    "$DB_NAME" "$TEMP_DB"

echo "  ✅ aligned 포맷 복사본 생성: $TEMP_DB"

# ─────────────────────────────────────
# 2. aligned DB를 dump
# ─────────────────────────────────────
echo ""
echo "[2/3] Dump 생성..."
"$NEO4J_ADMIN" database dump "$TEMP_DB" \
    --to-path="$BACKUP_DIR" \
    --overwrite-destination=true

# dump 파일명을 neo4j.dump으로 변경 (서버에서 load 시 DB명과 일치해야 함)
if [ -f "$BACKUP_DIR/${TEMP_DB}.dump" ]; then
    mv "$BACKUP_DIR/${TEMP_DB}.dump" "$BACKUP_DIR/${DB_NAME}.dump"
fi

# ─────────────────────────────────────
# 3. 임시 DB 정리
# ─────────────────────────────────────
echo ""
echo "[3/3] 임시 파일 정리..."
rm -rf "$TEMP_DB_DIR" "$TEMP_TX_DIR" 2>/dev/null || true
echo "  ✅ 임시 DB ($TEMP_DB) 삭제"

# ─────────────────────────────────────
# 결과
# ─────────────────────────────────────
if [ -f "$BACKUP_DIR/${DB_NAME}.dump" ]; then
    SIZE=$(du -h "$BACKUP_DIR/${DB_NAME}.dump" | cut -f1)
    echo ""
    echo "========================================="
    echo "  ✅ Dump 생성 완료!"
    echo "========================================="
    echo "  파일: backups/${DB_NAME}.dump"
    echo "  크기: $SIZE"
    echo "  포맷: aligned (Community Edition 호환)"
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
