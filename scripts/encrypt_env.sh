#!/bin/bash
# .env 파일을 암호화하여 .env.enc 생성
# 사용법: ./scripts/encrypt_env.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

ENV_FILE="$PROJECT_DIR/.env"
ENC_FILE="$PROJECT_DIR/.env.enc"

if [ ! -f "$ENV_FILE" ]; then
    echo "Error: .env 파일이 없습니다: $ENV_FILE"
    exit 1
fi

echo "=== .env 파일 암호화 ==="
echo "암호를 입력하세요 (서버에서 복호화 시 동일한 암호 필요):"
openssl enc -aes-256-cbc -salt -pbkdf2 -in "$ENV_FILE" -out "$ENC_FILE"

echo ""
echo "암호화 완료: $ENC_FILE"
echo "이 파일을 git에 commit/push 하세요."
