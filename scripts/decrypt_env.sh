#!/bin/bash
# .env.enc 파일을 복호화하여 .env 생성
# 사용법: ./scripts/decrypt_env.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

ENC_FILE="$PROJECT_DIR/.env.enc"
ENV_FILE="$PROJECT_DIR/.env"

if [ ! -f "$ENC_FILE" ]; then
    echo "Error: .env.enc 파일이 없습니다: $ENC_FILE"
    exit 1
fi

echo "=== .env.enc 파일 복호화 ==="
echo "암호화 시 사용한 암호를 입력하세요:"
openssl enc -aes-256-cbc -d -pbkdf2 -in "$ENC_FILE" -out "$ENV_FILE"

echo ""
echo "복호화 완료: $ENV_FILE"
