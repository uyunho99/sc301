#!/bin/bash
# EC2 서버 초기 세팅 스크립트
# SSM 접속 후 서버에서 실행
# 사용법: bash setup_server.sh

set -e

echo "========================================="
echo "  SC301 서버 세팅 시작"
echo "========================================="

# ─────────────────────────────────────
# 0. 홈 디렉토리로 이동 (SSM 기본 위치 보정)
# ─────────────────────────────────────
cd /home/ssm-user 2>/dev/null || cd ~
export HOME=$(pwd)
echo "작업 디렉토리: $HOME"

# ─────────────────────────────────────
# 1. 시스템 패키지 업데이트 + 기본 도구
# ─────────────────────────────────────
echo ""
echo "[1/6] 시스템 패키지 업데이트..."
sudo apt-get update -y
sudo apt-get install -y \
    software-properties-common \
    curl wget gnupg lsb-release \
    build-essential

# ─────────────────────────────────────
# 2. Python 3 + venv 패키지 설치
# ─────────────────────────────────────
echo ""
echo "[2/6] Python 설치..."
if python3 --version 2>/dev/null | grep -qE "3\.(11|12|13)"; then
    echo "Python 이미 설치됨: $(python3 --version)"
else
    sudo add-apt-repository -y ppa:deadsnakes/ppa
    sudo apt-get update -y
    sudo apt-get install -y python3.11 python3.11-venv python3.11-distutils
    sudo update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.11 1
fi
python3 --version

# venv 패키지 설치 (Ubuntu 24.04 필수)
sudo apt-get install -y python3-venv python3-pip

# ─────────────────────────────────────
# 3. Git 설치
# ─────────────────────────────────────
echo ""
echo "[3/6] Git 설치..."
if ! command -v git &> /dev/null; then
    sudo apt-get install -y git
fi
git --version

# ─────────────────────────────────────
# 4. Neo4j 설치 (Community Edition)
# ─────────────────────────────────────
echo ""
echo "[4/6] Neo4j 설치..."
if command -v neo4j &> /dev/null; then
    echo "Neo4j 이미 설치됨: $(neo4j --version 2>/dev/null || echo 'installed')"
else
    # Java 17 (Neo4j 5.x 필수)
    sudo apt-get install -y openjdk-17-jre-headless

    # Neo4j 공식 리포지토리 추가
    curl -fsSL https://debian.neo4j.com/neotechnology.gpg.key | sudo gpg --dearmor -o /usr/share/keyrings/neo4j.gpg
    echo "deb [signed-by=/usr/share/keyrings/neo4j.gpg] https://debian.neo4j.com stable latest" | sudo tee /etc/apt/sources.list.d/neo4j.list
    sudo apt-get update -y
    sudo apt-get install -y neo4j

    # 초기 비밀번호 설정 (password)
    sudo neo4j-admin dbms set-initial-password password

    # 서비스 시작 + 부팅 시 자동 실행
    sudo systemctl enable neo4j
    sudo systemctl start neo4j

    echo "Neo4j 설치 완료. bolt://localhost:7687 로 접속 가능"
fi

# ─────────────────────────────────────
# 5. 프로젝트 클론 + .env 복호화
# ─────────────────────────────────────
echo ""
echo "[5/6] 프로젝트 클론..."
REPO_URL="https://github.com/uyunho99/sc301.git"
PROJECT_DIR="$HOME/sc301"

if [ -d "$PROJECT_DIR" ]; then
    echo "기존 프로젝트 존재. git pull 진행..."
    cd "$PROJECT_DIR"
    git pull origin main
else
    git clone "$REPO_URL" "$PROJECT_DIR"
    cd "$PROJECT_DIR"
fi

echo ""
echo ".env 복호화..."
if [ -f "scripts/decrypt_env.sh" ] && [ -f ".env.enc" ]; then
    bash scripts/decrypt_env.sh
elif [ ! -f ".env" ]; then
    echo "⚠ .env.enc 없음. 수동으로 .env 생성 필요."
fi

# ─────────────────────────────────────
# 6. Python 가상환경 + 의존성 설치
# ─────────────────────────────────────
echo ""
echo "[6/6] Python 가상환경 생성 + 패키지 설치..."
VENV_DIR="$PROJECT_DIR/.venv"

if [ ! -d "$VENV_DIR" ]; then
    python3 -m venv "$VENV_DIR"
    echo "가상환경 생성: $VENV_DIR"
fi

source "$VENV_DIR/bin/activate"
pip install --upgrade pip
pip install -r requirements.txt

# ─────────────────────────────────────
# 완료
# ─────────────────────────────────────
echo ""
echo "========================================="
echo "  세팅 완료!"
echo "========================================="
echo ""
echo "프로젝트 경로 : $PROJECT_DIR"
echo "가상환경 경로 : $VENV_DIR"
echo "Neo4j (로컬)  : bolt://localhost:7687 (neo4j/password)"
echo "Neo4j (Aura)  : .env 파일의 NEO4J_AURA_URI 참조"
echo ""
echo "실행 방법:"
echo "  cd $PROJECT_DIR"
echo "  source .venv/bin/activate"
echo "  python cli.py repl --db local   # 로컬 Neo4j"
echo "  python cli.py repl --db aura    # AuraDB"
echo ""
echo "Neo4j 상태 확인:"
echo "  sudo systemctl status neo4j"
