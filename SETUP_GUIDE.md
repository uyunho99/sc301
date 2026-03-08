# SC301 Graph RAG 챗봇 설정 가이드

## 파일 구조

```
sc301/
+-- .env                        # 환경 변수 설정 (gitignore)
+-- .env.enc                    # 암호화된 환경 변수 (git 관리)
+-- __init__.py                 # 패키지 초기화 (Core, FlowEngine, ConversationState 공개)
+-- requirements.txt            # Python 의존성 (openai, neo4j, rdflib, python-dotenv, numpy)
|
|  -- 코어 모듈 --
+-- cli.py                      # CLI 인터페이스 (8개 커맨드)
+-- core.py                     # OpenAI + Neo4j + Q&A 벡터 스토어 통합 (CoreConfig, Core)
+-- state.py                    # 세션 상태 관리 (ConversationState, FileStateStorage, RedisStateStorage)
+-- rag_store.py                # Q&A 벡터 스토어 (jisikin JSONL+NPZ, 코사인 유사도 검색)
|
|  -- flow/ 패키지 (비즈니스 로직) --
+-- flow/
|   +-- __init__.py             # FlowEngine, StepInfo, TransitionResult export
|   +-- _types.py               # 데이터 클래스 (StepInfo, TransitionResult, TurnContext)
|   +-- engine.py               # FlowEngine: Mixin 조합 + 캐시 관리
|   +-- persona.py              # PersonaMixin: Persona 판별/Scenario 할당
|   +-- navigation.py           # NavigationMixin: Step 전이, 분기 평가
|   +-- slots.py                # SlotMixin: LLM 슬롯 추출, 자동 계산, 조건부 스킵
|   +-- consultation.py         # ConsultationMixin: 상담 Persona 스코어링
|   +-- rag_intent.py           # RAGIntentMixin: Hybrid RAG 의도 분류 + 컨텍스트 조합
|   +-- prompt.py               # PromptMixin: Step 유형별 프롬프트 생성
|   +-- turn.py                 # TurnMixin: process_turn 오케스트레이션 (동기/스트리밍/비동기)
|
|  -- schema/ 패키지 (Neo4j 스키마 + 비즈니스 룰) --
+-- schema/
|   +-- __init__.py             # 하위 호환: from schema import X 유지
|   +-- queries.py              # Cypher 쿼리 상수 (Flow 조회, 벡터 검색)
|   +-- ingestion.py            # TTL Ingestion 관련 Cypher (노드 Merge, 관계 생성)
|   +-- branching_rules.py      # BRANCHING_RULES 정적 라우팅 테이블
|   +-- rule_conditions.py      # RULE_CONDITION_MAP, OR_LOGIC_RULES
|   +-- guide_rules.py          # GUIDE_SELECTION_RULES
|   +-- slot_rules.py           # AUTO_COMPUTABLE_SLOTS, CONDITIONAL_SKIP_RULES, CHECKITEM_HINTS
|   +-- consultation_config.py  # 상담 키워드/톤/전략 데이터
|
|  -- jisikin/ (Q&A 벡터 스토어 데이터) --
+-- jisikin/
|   +-- rag_docs.jsonl          # 165,009건 Q&A 문서 (네이버 지식인)
|   +-- rag_docs.embeddings.npz # 사전 계산 임베딩 (text-embedding-3-small, 1536d)
|   +-- build_embeddings.py     # 임베딩 재생성 스크립트 (OpenAI API 사용)
|   +-- rag_docs.json           # 원본 JSON (참고용)
|
|  -- 그래프 유지보수 --
+-- patch_graph.py              # Neo4j 그래프 패치 스크립트 (3 패치셋)
+-- neo4j-aligned-schema.cypher # 정렬된 Neo4j 스키마 파일
|
|  -- 테스트 / 벤치마크 --
+-- test_scenarios.py           # 단위/통합 테스트 20개 (Neo4j 직접, LLM 불필요)
+-- test_repl.py                # REPL 시뮬레이션 14개 (TEST_SCENARIOS dict)
+-- test_persona_identification.py  # 페르소나 식별 테스트
+-- benchmark_scenarios.py      # 성능 벤치마크 (test_repl.py의 시나리오 사용)
|
|  -- 스크립트 --
+-- scripts/
|   +-- encrypt_env.sh          # 로컬: .env -> .env.enc 암호화 (AES-256-CBC)
|   +-- decrypt_env.sh          # 서버: .env.enc -> .env 복호화
|   +-- setup_server.sh         # 서버 초기 세팅 (Python + Neo4j + clone + pip + 데이터 복원)
|   +-- export_neo4j.py         # 로컬: Neo4j -> backups/neo4j_export.cypher 내보내기
|   +-- import_neo4j.sh         # 서버: Cypher 파일로 Neo4j 데이터 임포트
|   +-- dump_neo4j_local.sh     # 로컬: Neo4j Desktop -> backups/neo4j.dump
|   +-- restore_neo4j.sh        # 서버: .dump 파일로 Neo4j 데이터 복원
|
|  -- 문서 --
+-- CODE_SPECIFICATION.md       # 코드 명세서 (모듈별 메서드/구조)
+-- SETUP_GUIDE.md              # 이 파일
+-- DEPLOYMENT_GUIDE.md         # AWS EC2 배포 가이드
+-- SERVER_GUIDE.md             # 서버 관리 가이드
+-- GRAPH_RAG_SPEC.md           # Graph RAG 설계 명세
+-- TEST_SCENARIOS_GUIDE.md     # 테스트 시나리오 가이드 (턴별 상세)
+-- REPL_SCENARIOS_DETAIL.md    # REPL 14개 시나리오 턴별 상세
|
|  -- 데이터 --
+-- backups/                    # Neo4j 백업 (neo4j.dump, neo4j_export.cypher)
+-- states/                     # 세션 상태 저장 디렉토리 (gitignore)
```

### 테스트/벤치마크 파일 의존 관계

```
test_repl.py ---- TEST_SCENARIOS (14개 시나리오 + 발화 데이터)
  |                         |
  |                         +--> benchmark_scenarios.py (import해서 사용)
  |                                InstrumentedCore/FlowEngine 래퍼로 시간 측정
  |
  +-- flow/, state.py, schema/ (공유)

test_scenarios.py ---- 독립 실행 (TEST_SCENARIOS 미사용)
  |                    walk_scenario()로 slot 직접 주입 + assert 검증
  +-- flow/, state.py, schema/ (공유)
```

## 필수 설정 사항

### 1. .env 파일 설정

`.env` 파일에 다음 값을 설정해야 합니다:

```bash
# OpenAI
OPENAI_API_KEY=sk-proj-...
OPENAI_EMBEDDING_MODEL=text-embedding-3-small
OPENAI_CHAT_MODEL=gpt-4o
SLOT_EXTRACTION_MODEL=gpt-4o-mini

# Neo4j AuraDB (클라우드)
NEO4J_AURA_URI=neo4j+s://a3c4f112.databases.neo4j.io
NEO4J_AURA_USER=neo4j
NEO4J_AURA_PASSWORD=<실제_비밀번호>

# Neo4j Local (로컬)
NEO4J_LOCAL_URI=bolt://localhost:7687
NEO4J_LOCAL_USER=neo4j
NEO4J_LOCAL_PASSWORD=password

# 상태 저장소
STATE_BACKEND=file
STATE_STORAGE_DIR=./states
```

AuraDB 비밀번호 확인 방법:
1. https://console.neo4j.io/ 접속
2. 인스턴스 (a3c4f112) 선택
3. "Connect" 또는 "Connection details" 클릭
4. 비밀번호 확인 (처음 생성시 표시됨, 분실시 재생성 필요)

---

## 실행 방법

### Python 의존성 설치

```bash
cd sc301
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### jisikin/ Q&A 벡터 스토어 설정

임베딩이 이미 생성되어 있으면 (`jisikin/rag_docs.embeddings.npz`) 추가 작업 불필요.
numpy 버전 호환 문제 등으로 NPZ 로드 실패 시 임베딩 재생성:

```bash
# 임베딩 재생성 (OpenAI API 키 필요, ~165K 문서)
python jisikin/build_embeddings.py

# 배치 크기 변경 (기본: 100)
python jisikin/build_embeddings.py --batch-size 200
```

### 수동 설정

```bash
# 1. 스키마 설정 (벡터 인덱스, 제약조건 등)
python cli.py setup-schema --db local

# 2. 연결 상태 확인
python cli.py health --db local

# 3. 대화형 REPL 실행
python cli.py repl --db local

# 4. 모델 선택 (선택사항)
python cli.py repl --db local --model gpt-5       # gpt-5 모델 사용
python cli.py repl --db local --model gpt-4o      # gpt-4o 모델 사용 (기본값)
```

### CLI 명령어 전체 목록

| 명령어 | 용도 |
|--------|------|
| `python cli.py setup-schema --db local` | Neo4j 스키마 설정 (벡터 인덱스 등) |
| `python cli.py ingest <ttl_path> --db local` | TTL 파일 Neo4j 적재 |
| `python cli.py health --db local` | 연결 상태 확인 |
| `python cli.py repl --db local` | 대화형 REPL (스트리밍) |
| `python cli.py repl --db local --fast` | Fast 모드 (gpt-4o-mini, 응답 길이 제한) |
| `python cli.py repl --db local --model gpt-5` | GPT-5 모델 사용 |
| `python cli.py repl --db local --consultation-scoring off` | 상담 Persona 스코어링 비활성화 |
| `python cli.py repl --db local --intent-mode rule` | 의도 분류 rule-only 모드 |
| `python cli.py repl-async --db local` | 비동기 REPL 모드 |
| `python cli.py turn <session_id> "<text>" --db local` | 단일 턴 실행 |
| `python cli.py query "<cypher>" --db local` | Cypher 쿼리 직접 실행 (디버그) |
| `python cli.py sessions` | 저장된 세션 목록 |

> `--db` 옵션: `aura` (AuraDB 클라우드, 기본값) 또는 `local` (로컬 Neo4j)
> `--model` 옵션: `gpt-4o` (기본값) 또는 `gpt-5`
> `--consultation-scoring` 옵션: `hybrid` (기본값), `llm`, `off`
> `--intent-mode` 옵션: `rule`, `llm`, `hybrid` (기본값) — Hybrid RAG 의도 분류 모드

### REPL 내부 명령어

| 명령어 | 용도 |
|--------|------|
| `/state` | 현재 상태 출력 (페르소나, 스텝, 슬롯, 상담 Persona 스코어) |
| `/reset` | 세션 초기화 |
| `/cache` | 캐시 상태 출력 (임베딩, 스텝, 페르소나 캐시) |
| `/clear-cache` | 캐시 초기화 |
| `quit` / `exit` / `q` | 종료 |

---

## 테스트 실행

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

## 사용 예시

### REPL 모드
```bash
python cli.py repl --db local

# 출력 예시:
SC301 챗봇 REPL 시작 (세션: abc12345)
Neo4j: LOCAL 모드
모델: 응답=gpt-4o, 슬롯추출=gpt-4o-mini
스트리밍 모드 활성화
상담 Persona 스코어링: hybrid 모드
의도 분류 모드: hybrid
종료하려면 'quit' 또는 'exit'를 입력하세요.

Bot: 안녕하세요! 성형외과 상담 챗봇입니다. 어떤 상담이 필요하신가요?

You: 안녕하세요, 가슴 지방이식 상담 받고 싶어요
Bot: 안녕하세요! 가슴 지방이식 상담을 원하시는군요...

You: /state  # 현재 상태 확인
You: /reset  # 세션 초기화
You: quit    # 종료
```

### 단일 턴 실행
```bash
python cli.py turn my-session "가슴 확대 비용이 궁금해요" --db local
python cli.py turn my-session "가슴 확대 비용이 궁금해요" --db local --model gpt-5
```

---

## 아키텍처 설명

### Turn 내부 플로우 (process_turn)

```
+--------------------------------------------------------------+
| 1. State 로드                                                 |
|    - file/redis에서 session_id로 조회                         |
+--------------------------------------------------------------+
                           |
                           v
+--------------------------------------------------------------+
| 2. Persona/Scenario 결정 (첫 턴만)                            |
|    - 키워드 매칭 -> LLM 추론으로 페르소나 결정                |
|    - 시나리오의 시작 Step 설정                                 |
+--------------------------------------------------------------+
                           |
                           v
+--------------------------------------------------------------+
| 3. 병렬 3-way 실행 (ThreadPoolExecutor)                       |
|    +-- Slot Extraction: LLM으로 사용자 발화에서 값 추출       |
|    +-- GraphRAG 검색: Neo4j 벡터 인덱스 (Surgery + Step)      |
|    +-- QA 검색: jisikin/ 165K 문서 코사인 유사도 검색          |
+--------------------------------------------------------------+
                           |
                           v
+--------------------------------------------------------------+
| 3.5 Auto-compute Slots                                        |
|    - bmi: bodyInfo에서 자동 계산                               |
|    - regionBucket: residenceCountry/domesticDistrict에서 도출  |
+--------------------------------------------------------------+
                           |
                           v
+--------------------------------------------------------------+
| 3.6 Stale Step 감지 (STALE_STEP_THRESHOLD = 3)               |
|    - 동일 스텝 3턴 이상 체류 시 미수집 항목 -> '미응답' 처리  |
|    - confirm/finalize 스텝은 제외                              |
+--------------------------------------------------------------+
                           |
                           v
+--------------------------------------------------------------+
| 3.7 상담 Persona 스코어링 (hybrid 모드)                       |
|    - 규칙 기반 키워드 매칭 + LLM 추론 (4차원 점수)            |
|    - 누적 점수 6.0 이상 시 Persona 확정                       |
|    - 확정 후 톤/전략 프롬프트에 반영                           |
+--------------------------------------------------------------+
                           |
                           v
+--------------------------------------------------------------+
| 3.8 Hybrid RAG 의도 분류 + 컨텍스트 조합                      |
|    - _classify_user_intent(): slot_data / general_question /  |
|      mixed (rule/llm/hybrid 모드)                              |
|    - _assemble_rag_context(): 의도별 가중치로 조합             |
|    - general_question이면 offscript 템플릿 적용                |
+--------------------------------------------------------------+
                           |
                           v
+--------------------------------------------------------------+
| 4. Step Transition (다음 단계 결정)                           |
|    - BRANCHING_RULES -> RULE_CONDITION_MAP -> TO 체인         |
|    - 조건 충족시 다음 Step으로 이동                            |
+--------------------------------------------------------------+
                           |
                           v
+--------------------------------------------------------------+
| 4.5 Chain Through Empty Steps                                 |
|    - inform 스텝(CheckItem 없음) 자동 건너뛰기                |
|    - 건너뛴 inform의 Guide/Program 안내 내용 수집              |
+--------------------------------------------------------------+
                           |
                           v
+--------------------------------------------------------------+
| 5. Response Generation                                        |
|    - Step 유형별 프롬프트 생성 (collect/inform/confirm/...)    |
|    - 건너뛴 inform 안내 + Hybrid RAG context + history 포함   |
|    - 상담 Persona 톤/전략 반영                                 |
|    - LLM으로 최종 응답 생성 (스트리밍 지원)                    |
+--------------------------------------------------------------+
                           |
                           v
+--------------------------------------------------------------+
| 6. State 저장                                                 |
|    - new current_step, slots, history, consultation 반영      |
+--------------------------------------------------------------+
```

### Neo4j 그래프 구조

```
(Persona)--[:HAS_SCENARIO]-->(Scenario)
                                |
                    +--[:startsAt]--+
                    |               |
                    v               |
                 (Step)--[:TO]-->(Step)--[:TO]-->...
                    |
            [:checks]
                    |
                    v
              (CheckItem)

(Step)--[:hasGuide]-->(Guide)
(Step)--[:recommends]-->(Program)
(Step)--[:hasOption]-->(Option)--[:targets]-->(Surgery)
(Surgery)--[:causeSideEffect]-->(SideEffect)

분기 관련:
(Step)--[:CONSIDERS]-->(DecisionRule)--[:WHEN]-->(ConditionGroup)--[:HAS_CONDITION]-->(Condition)
(Transition)--[:from]-->(Step), [:to]-->(Step), [:decidedBy]-->(DecisionRule)
```

> Step 간 연결은 `:TO` 관계 사용 (`:leadsTo` 아님)
> 분기 우선순위: `BRANCHING_RULES` (정적) -> `RULE_CONDITION_MAP` -> `TO` 체인 (폴백)

---

## 문제 해결

### Neo4j 연결 실패
- 로컬: `bolt://localhost:7687` 접속 가능한지 확인, Neo4j Desktop에서 DB가 Started 상태인지 확인
- AuraDB: 콘솔에서 인스턴스가 "Running" 상태인지 확인
- 비밀번호가 정확한지 확인
- AuraDB URI가 `neo4j+s://`로 시작하는지 확인

### OpenAI API 오류
- API 키가 유효한지 확인
- 크레딧이 남아있는지 확인
- rate limit 초과 여부 확인

### Q&A 벡터 스토어 로드 실패
- NPZ 파일이 존재하는지 확인: `ls jisikin/rag_docs.embeddings.npz`
- numpy 버전 호환 문제 시 임베딩 재생성: `python jisikin/build_embeddings.py`
- pickle 캐시 오류 시 캐시 삭제 후 재시작: `rm rag_cache.pkl`

### Neo4j 데이터 복원 (2가지 방법)

| 방법 | 로컬 내보내기 | 서버 복원 | 특징 |
|------|-------------|----------|------|
| Cypher 텍스트 | `python scripts/export_neo4j.py` | `bash scripts/import_neo4j.sh` | Community Edition 호환, 텍스트 기반 |
| .dump 바이너리 | `bash scripts/dump_neo4j_local.sh` | `bash scripts/restore_neo4j.sh` | 빠름, block->aligned 변환 포함 |

---

## 추가 개발

### 새로운 시나리오 추가
1. Neo4j에서 Persona 노드 생성
2. Scenario 노드 생성 + `HAS_SCENARIO` 관계
3. Step 노드들 생성 + `:TO` 관계로 연결
4. CheckItem 노드 생성 + `:checks` 관계
5. `schema/branching_rules.py`에 `BRANCHING_RULES` 분기 추가
6. `schema/rule_conditions.py`에 `RULE_CONDITION_MAP` 조건 추가
7. 데이터 내보내기: `python scripts/export_neo4j.py`

### Q&A 데이터 업데이트
1. `jisikin/rag_docs.jsonl` 교체 (id, content, metadata.question, metadata.answer 형식)
2. 임베딩 재생성: `python jisikin/build_embeddings.py`
3. pickle 캐시 삭제: `rm rag_cache.pkl` (다음 실행 시 자동 재생성)
