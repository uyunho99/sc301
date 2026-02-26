#!/bin/bash
# Neo4j 데이터 복원 스크립트 (서버에서 실행)
# .dump 파일 사용 (Community Edition - aligned format)
# 사용법: bash scripts/restore_neo4j.sh

set -e

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
BACKUP_DIR="$PROJECT_DIR/backups"
DB_NAME="neo4j"

echo "========================================="
echo "  Neo4j 데이터 복원"
echo "========================================="

# ─────────────────────────────────────
# 1. Dump 파일 확인
# ─────────────────────────────────────
DUMP_FILE="$BACKUP_DIR/${DB_NAME}.dump"

if [ ! -f "$DUMP_FILE" ]; then
    # 날짜 태그 붙은 파일도 검색
    DUMP_FILE=$(ls -t "$BACKUP_DIR"/*.dump 2>/dev/null | head -1)
fi

if [ -z "$DUMP_FILE" ] || [ ! -f "$DUMP_FILE" ]; then
    echo "❌ backups/ 디렉토리에 .dump 파일이 없습니다."
    echo ""
    echo "로컬에서 dump 생성:"
    echo "  bash scripts/dump_neo4j_local.sh"
    echo ""
    echo "⚠ .backup 파일은 Enterprise Edition에서만 복원 가능합니다."
    echo "  Neo4j Desktop에서 dump_neo4j_local.sh 로 다시 생성해주세요."
    exit 1
fi

SIZE=$(du -h "$DUMP_FILE" | cut -f1)
echo "  Dump 파일: $(basename "$DUMP_FILE") ($SIZE)"
echo "  대상 DB:   $DB_NAME"
echo ""

# ─────────────────────────────────────
# 2. dump 파일명을 neo4j.dump로 맞추기
#    (neo4j-admin database load는 <db>.dump 파일명 기대)
# ─────────────────────────────────────
EXPECTED="$BACKUP_DIR/${DB_NAME}.dump"
if [ "$DUMP_FILE" != "$EXPECTED" ]; then
    echo "파일명 조정: $(basename "$DUMP_FILE") → ${DB_NAME}.dump"
    cp "$DUMP_FILE" "$EXPECTED"
fi

# ─────────────────────────────────────
# 3. dump 파일을 neo4j 유저가 접근 가능한 경로로 복사
#    (neo4j 유저는 /home/ssm-user/ 접근 불가)
# ─────────────────────────────────────
LOAD_DIR="/tmp/neo4j-restore"
sudo rm -rf "$LOAD_DIR"
sudo mkdir -p "$LOAD_DIR"
sudo cp "$EXPECTED" "$LOAD_DIR/${DB_NAME}.dump"
sudo chown -R neo4j:neo4j "$LOAD_DIR"

# ─────────────────────────────────────
# 4. Neo4j 중지
# ─────────────────────────────────────
echo "[1/4] Neo4j 중지..."
sudo systemctl stop neo4j 2>/dev/null || true
sleep 2

# ─────────────────────────────────────
# 5. 데이터 로드 (neo4j 유저로 실행)
# ─────────────────────────────────────
echo "[2/4] 데이터 로드..."
sudo -u neo4j neo4j-admin database load "$DB_NAME" \
    --from-path="$LOAD_DIR" \
    --overwrite-destination=true

echo "  ✅ 로드 완료"

# 임시 디렉토리 정리
sudo rm -rf "$LOAD_DIR"

# ─────────────────────────────────────
# 6. 파일 권한 보정
# ─────────────────────────────────────
echo "[3/4] 파일 권한 확인..."
sudo chown -R neo4j:neo4j /var/lib/neo4j/data/databases/"$DB_NAME" 2>/dev/null || true
sudo chown -R neo4j:neo4j /var/lib/neo4j/data/transactions/"$DB_NAME" 2>/dev/null || true

# ─────────────────────────────────────
# 7. Neo4j 재시작
# ─────────────────────────────────────
echo "[4/4] Neo4j 재시작..."
sudo systemctl start neo4j
sleep 5

# ─────────────────────────────────────
# 7. 상태 확인
# ─────────────────────────────────────
if sudo systemctl is-active --quiet neo4j; then
    echo ""
    echo "========================================="
    echo "  ✅ 복원 완료!"
    echo "========================================="
    echo "  DB: bolt://localhost:7687"
    echo "  인증: neo4j / password"
    echo ""

    # 노드 수 확인 (cypher-shell 있는 경우)
    if command -v cypher-shell &> /dev/null; then
        echo "데이터 확인 (Neo4j 준비 대기 중...):"
        for i in $(seq 1 15); do
            if cypher-shell -u neo4j -p password -a bolt://localhost:7687 \
                "MATCH (n) RETURN labels(n)[0] AS label, count(n) AS cnt ORDER BY cnt DESC;" 2>/dev/null; then
                break
            fi
            sleep 2
        done
    fi

    echo ""
    echo "실행: python cli.py --db local chat"
else
    echo ""
    echo "⚠ Neo4j 시작 실패. 로그 확인:"
    echo "  sudo journalctl -u neo4j -n 50"
fi
