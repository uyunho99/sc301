# 🚀 SC301 Graph RAG 챗봇 설정 가이드

## 📁 파일 구조

```
sc301/
├── .env                        # 환경 변수 설정 ⚠️ 수정 필요
├── __init__.py                 # 패키지 초기화
│
│  ── 코어 모듈 ──
├── cli.py                      # CLI 인터페이스
├── core.py                     # OpenAI + Neo4j 통합 (CoreConfig, Core)
├── flow.py                     # 대화 플로우 엔진 (FlowEngine)
├── schema.py                   # 분기 규칙, 스킵 조건, 자동 계산 정의
├── state.py                    # 세션 상태 관리 (ConversationState)
│
│  ── 테스트 / 벤치마크 ──
├── test_scenarios.py           # 단위/통합 테스트 20개 (Neo4j 직접, LLM 불필요)
├── test_repl.py                # REPL 시뮬레이션 14개 (TEST_SCENARIOS dict)
├── benchmark_scenarios.py      # 성능 벤치마크 (test_repl.py의 시나리오 사용)
│
│  ── 문서 ──
├── TEST_SCENARIOS_GUIDE.md     # 테스트 시나리오 가이드 (턴별 상세)
├── REPL_SCENARIOS_DETAIL.md    # REPL 14개 시나리오 턴별 상세
├── benchmark_analysis.md       # V1 벤치마크 리포트 (gpt-5)
├── benchmark_analysis_v2.md    # V2 벤치마크 리포트 (gpt-4o + gpt-4o-mini)
├── CODE_SPECIFICATION.md       # 코드 명세서 (모듈별 메서드/구조)
├── SETUP_GUIDE.md              # 이 파일
│
│  ── 데이터 ──
├── sample_ontology.ttl         # 온톨로지 데이터 (TTL)
├── requirements.txt            # 의존성 목록
└── states/                     # 세션 상태 저장 디렉토리
```

### 테스트/벤치마크 파일 의존 관계

```
test_repl.py ──── TEST_SCENARIOS (14개 시나리오 + 발화 데이터)
  │                         │
  │                         └──► benchmark_scenarios.py (import해서 사용)
  │                                InstrumentedCore/FlowEngine 래퍼로 시간 측정
  │
  └── flow.py, state.py, schema.py (공유)

test_scenarios.py ──── 독립 실행 (TEST_SCENARIOS 미사용)
  │                    walk_scenario()로 slot 직접 주입 + assert 검증
  └── flow.py, state.py, schema.py (공유)
```

## ⚠️ 필수 설정 사항

### 1. Neo4j 비밀번호 설정

`.env` 파일에서 `NEO4J_PASSWORD`를 실제 비밀번호로 변경해야 합니다.

AuraDB 비밀번호 확인 방법:
1. https://console.neo4j.io/ 접속
2. 인스턴스 (a3c4f112) 선택
3. "Connect" 또는 "Connection details" 클릭
4. 비밀번호 확인 (처음 생성시 표시됨, 분실시 재생성 필요)

```bash
# .env 파일 수정
NEO4J_PASSWORD=<실제_비밀번호>
```

## 🛠️ 실행 방법

### 방법 1: 자동 설정 스크립트 (권장)

```bash
cd sc301_layer
python setup_and_test.py
```

이 스크립트는 다음을 자동으로 수행합니다:
- 환경 변수 검증
- OpenAI 연결 테스트
- Neo4j 연결 테스트
- 스키마 설정
- TTL 데이터 적재
- 대화 테스트

### 방법 2: 수동 설정

```bash
# 1. 스키마 설정
python -m cli setup-schema

# 2. TTL 데이터 적재
python -m cli ingest sample_ontology.ttl

# 3. 연결 상태 확인
python -m cli health

# 4. 대화형 REPL 실행
python -m cli repl

# 5. 모델 선택 (선택사항)
python -m cli repl --model gpt-5       # gpt-5 모델 사용
python -m cli repl --model gpt-4o      # gpt-4o 모델 사용 (기본값)
```

## 🧪 테스트 실행

### 단위/통합 테스트 (test_scenarios.py)
```bash
# Neo4j 로컬 필요, LLM 불필요
python test_scenarios.py          # 20개 테스트 전체 실행
```

### REPL 시뮬레이션 (test_repl.py)
```bash
# 14개 시나리오, 기본: slot 직접 주입 (LLM 불필요)
python test_repl.py --db local -s all        # 전체 실행
python test_repl.py --db local -s p1std      # 특정 시나리오
python test_repl.py --db local -s p1std --step  # 턴마다 일시정지
python test_repl.py --db local -s p1std --with-llm  # 실제 LLM 사용
python test_repl.py --db local -s p1std --with-llm --model gpt-5  # gpt-5로 LLM 사용
python test_repl.py --db local -i            # 수동 입력 모드
```

### 성능 벤치마크 (benchmark_scenarios.py)
```bash
# LLM 필수 (OpenAI API 호출)
python benchmark_scenarios.py --db local              # 전체 벤치마크
python benchmark_scenarios.py --db local -s p1std      # 특정 시나리오
python benchmark_scenarios.py --db local --csv result.csv  # CSV 내보내기
```

> 상세 시나리오 목록과 턴별 데이터는 `TEST_SCENARIOS_GUIDE.md` 참고

---

## 💬 사용 예시

### REPL 모드
```bash
python -m cli repl

# 출력 예시:
🚀 SC301 챗봇 REPL 시작 (세션: abc12345)
종료하려면 'quit' 또는 'exit'를 입력하세요.

🤖 Bot: 안녕하세요! 성형외과 상담 챗봇입니다.

👤 You: 안녕하세요, 가슴 지방이식 상담 받고 싶어요
🤖 Bot: 안녕하세요! 가슴 지방이식 상담을 원하시는군요...

👤 You: /state  # 현재 상태 확인
👤 You: /reset  # 세션 초기화
👤 You: quit    # 종료
```

### 단일 턴 실행
```bash
python -m cli turn my-session "가슴 확대 비용이 궁금해요"
python -m cli turn my-session "가슴 확대 비용이 궁금해요" --model gpt-5
```

## 🏗️ 아키텍처 설명

### Turn 내부 플로우 (process_turn)

```
┌──────────────────────────────────────────────────────────────┐
│ 1. State 로드                                                │
│    - file/redis에서 session_id로 조회                        │
└──────────────────────────┬───────────────────────────────────┘
                           │
                           ▼
┌──────────────────────────────────────────────────────────────┐
│ 2. Persona/Scenario 결정 (첫 턴만)                           │
│    - 키워드 매칭 → LLM 추론으로 페르소나 결정                │
│    - 시나리오의 시작 Step 설정                                │
└──────────────────────────┬───────────────────────────────────┘
                           │
                           ▼
┌──────────────────────────────────────────────────────────────┐
│ 3. Slot Extraction (정보 추출)                               │
│    - 현재 Step + 시나리오 전체 미수집 CheckItem 통합 (Look-ahead) │
│    - LLM 1회 호출로 사용자 발화에서 값 추출                  │
│    - state.slots에 저장                                      │
└──────────────────────────┬───────────────────────────────────┘
                           │
                           ▼
┌──────────────────────────────────────────────────────────────┐
│ 3.5 Auto-compute Slots                                       │
│    - bmi: bodyInfo에서 자동 계산                              │
│    - regionBucket: residenceCountry/domesticDistrict에서 도출 │
└──────────────────────────┬───────────────────────────────────┘
                           │
                           ▼
┌──────────────────────────────────────────────────────────────┐
│ 3.6 Stale Step 감지 (STALE_STEP_THRESHOLD = 3)              │
│    - 동일 스텝 3턴 이상 체류 시 미수집 항목 → '미응답' 처리  │
│    - confirm/finalize 스텝은 제외                             │
└──────────────────────────┬───────────────────────────────────┘
                           │
                           ▼
┌──────────────────────────────────────────────────────────────┐
│ 4. Step Transition (다음 단계 결정)                          │
│    - BRANCHING_RULES → Transition+DecisionRule → TO → leadsTo│
│    - 조건 충족시 다음 Step으로 이동                           │
└──────────────────────────┬───────────────────────────────────┘
                           │
                           ▼
┌──────────────────────────────────────────────────────────────┐
│ 4.5 Chain Through Empty Steps                                │
│    - inform 스텝(CheckItem 없음) 자동 건너뛰기               │
│    - 건너뛴 inform의 Guide/Program 안내 내용 수집            │
└──────────────────────────┬───────────────────────────────────┘
                           │
                           ▼
┌──────────────────────────────────────────────────────────────┐
│ 5. Vector Search (RAG)                                       │
│    - Neo4j Vector Index에서 Surgery/SideEffect 검색          │
│    - 관련 정보를 context로 수집                              │
└──────────────────────────┬───────────────────────────────────┘
                           │
                           ▼
┌──────────────────────────────────────────────────────────────┐
│ 6. Response Generation                                       │
│    - Step 유형별 프롬프트 생성 (collect/inform/confirm/...)   │
│    - 건너뛴 inform 안내 내용 + RAG context + history 포함    │
│    - LLM으로 최종 응답 생성 (스트리밍 지원)                  │
└──────────────────────────┬───────────────────────────────────┘
                           │
                           ▼
┌──────────────────────────────────────────────────────────────┐
│ 7. State 저장                                                │
│    - new current_step, slots, history 반영                   │
└──────────────────────────────────────────────────────────────┘
```

### Neo4j 그래프 구조

```
(Persona)──[:HAS_SCENARIO]──>(Scenario)
                                │
                    ┌───[:startsAt]───┐
                    │                 │
                    ▼                 │
                 (Step)──[:TO]──>(Step)──[:TO]──>...
                    │
            [:checks]
                    │
                    ▼
              (CheckItem)

(Surgery)──[:causeSideEffect]──>(SideEffect)
```

> Step 간 연결은 `:TO` 관계 사용 (`:leadsTo` 아님)

## 🔧 문제 해결

### Neo4j 연결 실패
- AuraDB 콘솔에서 인스턴스가 "Running" 상태인지 확인
- 비밀번호가 정확한지 확인
- URI가 `neo4j+s://`로 시작하는지 확인

### OpenAI API 오류
- API 키가 유효한지 확인
- 크레딧이 남아있는지 확인
- rate limit 초과 여부 확인

### TTL 적재 실패
- TTL 파일 문법 확인 (Turtle 형식)
- 네임스페이스 프리픽스 확인

## 📚 추가 개발

### 새로운 시술 추가
`sample_ontology.ttl`에 Surgery 추가:
```turtle
sample:Surgery_NewProcedure rdf:type ont:Surgery ;
    ont:name "새로운 시술" ;
    ont:desc "시술 설명..." ;
    ont:category "카테고리" ;
    ont:causeSideEffect sample:SE_Swelling .
```

### 새로운 시나리오 추가
1. Persona 정의
2. Scenario 정의
3. Step들 정의 (leadsTo로 연결)
4. CheckItem 정의
5. `python -m cli ingest <새파일.ttl>` 실행
