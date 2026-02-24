#!/bin/bash
# Neo4j 덤프 복원 스크립트
# 서버에서 실행: bash scripts/restore_neo4j.sh

set -e

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
BACKUP_DIR="$PROJECT_DIR/backups"
DB_NAME="neo4j"

echo "========================================="
echo "  Neo4j 데이터 복원"
echo "========================================="

# .dump 파일 찾기
DUMP_FILE=$(ls -t "$BACKUP_DIR"/*.dump 2>/dev/null | head -1)

if [ -z "$DUMP_FILE" ]; then
    echo "❌ backups/ 디렉토리에 .dump 파일이 없습니다."
    exit 1
fi

echo "덤프 파일: $DUMP_FILE"
echo "대상 DB: $DB_NAME"
echo ""

# 1. Neo4j 중지
echo "[1/3] Neo4j 중지..."
sudo systemctl stop neo4j
sleep 2

# 2. 데이터 복원
echo "[2/3] 데이터 로드..."
sudo neo4j-admin database load $DB_NAME \
    --from-path="$BACKUP_DIR" \
    --overwrite-destination=true

echo "✅ 로드 완료"

# 3. Neo4j 재시작
echo "[3/3] Neo4j 재시작..."
sudo systemctl start neo4j
sleep 5

# 상태 확인
if sudo systemctl is-active --quiet neo4j; then
    echo ""
    echo "========================================="
    echo "  ✅ 복원 완료!"
    echo "========================================="
    echo "  DB: bolt://localhost:7687"
    echo "  인증: neo4j / password"
    echo ""
    echo "  확인: python cli.py --db local chat"
else
    echo ""
    echo "⚠ Neo4j 시작 실패. 로그 확인:"
    echo "  sudo journalctl -u neo4j -n 50"
fi
