#!/bin/bash
# EC2 서버 초기 세팅 스크립트
# SSM 접속 후 서버에서 실행
# 사용법: bash setup_server.sh

set -e

echo "=== SC301 서버 세팅 시작 ==="

# 1. 기본 패키지 업데이트
echo "[1/5] 시스템 패키지 업데이트..."
sudo yum update -y 2>/dev/null || sudo apt-get update -y 2>/dev/null

# 2. Python 3 & pip 설치 확인
echo "[2/5] Python 환경 확인..."
if ! command -v python3 &> /dev/null; then
    sudo yum install -y python3 python3-pip 2>/dev/null || sudo apt-get install -y python3 python3-pip 2>/dev/null
fi
python3 --version
pip3 --version 2>/dev/null || python3 -m pip --version

# 3. Git 설치 확인
echo "[3/5] Git 확인..."
if ! command -v git &> /dev/null; then
    sudo yum install -y git 2>/dev/null || sudo apt-get install -y git 2>/dev/null
fi
git --version

# 4. 프로젝트 클론
echo "[4/5] 프로젝트 클론..."
REPO_URL="https://github.com/uyunho99/sc301.git"
PROJECT_DIR="$HOME/sc301"

if [ -d "$PROJECT_DIR" ]; then
    echo "기존 프로젝트 디렉토리가 있습니다. pull 진행..."
    cd "$PROJECT_DIR"
    git pull
else
    git clone "$REPO_URL" "$PROJECT_DIR"
    cd "$PROJECT_DIR"
fi

# 5. .env 복호화
echo "[5/5] .env 복호화..."
if [ -f "scripts/decrypt_env.sh" ]; then
    bash scripts/decrypt_env.sh
else
    echo "Warning: decrypt_env.sh 가 없습니다. 수동으로 .env 설정 필요."
fi

# 6. Python 의존성 설치
echo "[추가] Python 패키지 설치..."
if [ -f "requirements.txt" ]; then
    pip3 install -r requirements.txt
else
    echo "requirements.txt 없음. 수동 설치 필요."
fi

echo ""
echo "=== 세팅 완료 ==="
echo "프로젝트 경로: $PROJECT_DIR"
echo ""
echo "실행 방법:"
echo "  cd $PROJECT_DIR"
echo "  python3 cli.py --db aura chat"
