# SC301 Graph RAG Chatbot - Code Specification

> **Date:** 2026-02-23
> **Version:** v3 (Persona disambiguation, prefetch slots, signal rules, patch_graph)

---

## 1. Architecture Overview

SC301은 **Graph RAG 기반 성형외과(가슴성형) 상담 챗봇**으로, Neo4j 그래프 DB에 저장된 온톨로지(Persona → Scenario → Step)를 따라가며 사용자와 대화를 진행하는 시스템이다.

### 핵심 설계 원칙

- **Graph-Driven Flow**: 대화 흐름이 하드코딩이 아닌 Neo4j 그래프의 Step → Step 관계로 정의됨
- **Slot-Based State Management**: 각 Step에서 수집해야 할 정보(CheckItem)를 slot으로 관리, 모두 수집 시 다음 Step으로 전이
- **LLM-Powered Extraction + Generation**: OpenAI LLM이 사용자 발화에서 slot 값을 추출하고, 상황에 맞는 응답을 생성
- **Static Routing Table**: 분기 로직은 DB의 Transition/DecisionRule 노드 대신 Python dict(`BRANCHING_RULES`)로 관리하여 성능과 디버깅 편의성 확보

---

## 2. Main Workflow (턴 처리 파이프라인)

사용자의 한 마디(턴) 입력부터 응답 생성까지의 전체 흐름:

```
User Input
    │
    ▼
┌──────────────────────────────────────────────────────────────┐
│ 1. state.add_turn("user", text)                              │
│    사용자 입력을 대화 히스토리에 기록                          │
├──────────────────────────────────────────────────────────────┤
│ 2. flow.resolve_persona_scenario(state, text)                │
│    ┌─ 첫 턴: 키워드+복합신호 기반 Persona 판별               │
│    │   → 모호하면 disambiguation 질문 반환 (턴 종료)         │
│    │   → 명확하면 Persona → Scenario → 시작 Step 할당        │
│    └─ 이미 시작됨: 스킵                                      │
├──────────────────────────────────────────────────────────────┤
│ 3. flow.extract_slots(state, text)     ←┐                    │
│    현재 Step의 CheckItem 값을 LLM으로 추출 │ 병렬 실행       │
│    + n+1 Step prefetch (비분기 시)        │ (ThreadPool)     │
│ 5. core.vector_search_combined(text)   ←┘                    │
│    Surgery + Step 벡터 검색 (RAG context)                     │
├──────────────────────────────────────────────────────────────┤
│ 3.5. flow.auto_compute_slots(state)                          │
│      bmi, regionBucket 등 파생 슬롯 자동 계산                │
├──────────────────────────────────────────────────────────────┤
│ 3.6. Stale step 감지 (동일 Step 3턴 이상 → 미수집을 '미응답')│
├──────────────────────────────────────────────────────────────┤
│ 4. flow.next_step(state)                                     │
│    다음 Step 결정 (평가 순서):                                │
│    ① BRANCHING_RULES 조건 평가 → 분기                       │
│    ② TO 관계 → 단일/다중 경로                               │
│    ③ leadsTo 레거시 fallback                                │
│    ④ None → 시나리오 종료                                   │
│                                                              │
│    protocolMode가 분기에서 설정되면 state에 반영              │
│    state.move_to_step() + prefetch_slots 승격                │
├──────────────────────────────────────────────────────────────┤
│ 4.5. flow._chain_through_empty_steps(state)                  │
│      inform 스텝 등 CheckItem 없는 스텝 연쇄 건너뛰기       │
│      → 건너뛴 inform의 Guide/Program 안내 내용 수집         │
├──────────────────────────────────────────────────────────────┤
│ 6. flow.build_step_prompt(step_id, state, rag_context)       │
│    Step 유형별 시스템 프롬프트 생성                           │
│    + 건너뛴 inform 안내 내용을 프롬프트 앞에 삽입            │
├──────────────────────────────────────────────────────────────┤
│ 7. LLM 응답 생성 (streaming / blocking / async)              │
├──────────────────────────────────────────────────────────────┤
│ 8. state.add_turn("assistant", response)                     │
│    state 저장 (FileStorage / Redis)                          │
└──────────────────────────────────────────────────────────────┘
    │
    ▼
Bot Response
```

---

## 3. Module Dependency

```
             ┌──────────┐
             │  cli.py  │  ← 진입점 (argparse CLI)
             └────┬─────┘
                  │
        ┌─────────┼──────────┐
        ▼         ▼          ▼
   ┌─────────┐ ┌─────────┐ ┌──────────┐
   │ core.py │ │ flow.py │ │ state.py │
   │ (인프라) │ │(비즈니스)│ │ (상태)   │
   └────┬────┘ └────┬────┘ └──────────┘
        │           │          ▲
        │           └──────────┘ (flow가 state를 조작)
        │           │
        ▼           ▼
   ┌──────────────────┐
   │    schema.py     │  ← Cypher 쿼리 + 정적 라우팅 테이블
   └──────────────────┘

독립 스크립트:
   ┌──────────────┐
   │ patch_graph.py│  ← Neo4j 그래프 패치 (일회성 마이그레이션)
   └──────────────┘

External:
  - OpenAI API (core.py → embedding/chat, flow.py → slot추출/응답)
  - Neo4j DB (core.py → 연결관리, flow.py → 쿼리 실행)
```

---

## 4. Directory Structure

```
sc301/
├── __init__.py              # 패키지 초기화 (ConversationState, Core, FlowEngine export)
├── schema.py                # Cypher 쿼리 상수 + 정적 라우팅 테이블 + TTL 네임스페이스
├── flow.py                  # FlowEngine: 턴 처리, 분기 평가, 슬롯 추출, 프롬프트 생성
├── state.py                 # ConversationState + Storage (File/Redis)
├── core.py                  # Core: OpenAI + Neo4j + Embedding + Vector Search + TTL Ingestion
├── cli.py                   # CLI 진입점 (8개 서브커맨드)
├── patch_graph.py           # Neo4j 그래프 패치 스크립트 (개인정보, P5 분리, CONSIDERS 보완)
├── test_scenarios.py        # 단위/통합 테스트
├── test_repl.py             # REPL 시뮬레이션 테스트
├── test_persona_identification.py  # Persona 판별 테스트
├── benchmark_scenarios.py   # 성능 벤치마크
├── requirements.txt         # Python 의존성
├── .env                     # 환경변수 (API 키, DB 접속 정보)
├── states/                  # 세션 상태 JSON 파일 저장 디렉토리
├── GRAPH_RAG_SPEC.md        # Graph RAG 전체 스펙 문서
├── TEST_SCENARIOS_GUIDE.md  # 테스트 시나리오 가이드
├── REPL_SCENARIOS_DETAIL.md # REPL 시나리오 상세
└── SETUP_GUIDE.md           # 환경 설정 가이드
```

---

## 5. File-by-File Specification

### 5.1. `schema.py` — Cypher 쿼리 & 정적 라우팅 테이블

> Neo4j 스키마 정의, 모든 Cypher 쿼리 상수, 분기/스킵/계산 규칙 테이블

#### 상수 카테고리

| 카테고리 | 상수명 | 개수 | 설명 |
|----------|--------|------|------|
| 네임스페이스 | `TTL_NAMESPACES` | 3 | ont, sample, webprotege URI |
| 스키마 생성 | `SCHEMA_QUERIES` | 14 | Uniqueness Constraints |
| 벡터 인덱스 | `VECTOR_INDEX_QUERIES` | 3 | Surgery, Step, CheckItem 벡터 인덱스 |
| Flow 조회 | `QUERY_ALL_PERSONAS` 등 | 13 | Persona/Scenario/Step/CheckItem/Option 조회 |
| 벡터 검색 | `QUERY_VECTOR_SEARCH_*` | 2 | Surgery, Step 벡터 검색 |
| 노드 Merge | `QUERY_MERGE_*` | 14 | Persona~Threshold 노드 MERGE |
| 관계 생성 | `QUERY_CREATE_REL_*` | 18 | 모든 관계 타입 MERGE |
| 임베딩 | `QUERY_UPDATE_EMBEDDING` | 1 | 노드 임베딩 업데이트 |

#### 정적 라우팅 테이블

| 테이블 | 설명 |
|--------|------|
| `BRANCHING_RULES` | 5개 분기점(sourceStepId) → 총 16개 규칙. `{transitionId, ruleId, targetStepId, priority, isDefault}` |
| `RULE_CONDITION_MAP` | DecisionRule ID → 관련 Condition ID 리스트 (14 규칙) |
| `OR_LOGIC_RULES` | OR 로직 사용 DecisionRule 집합 (기본은 AND) |
| `GUIDE_SELECTION_RULES` | 9개 Step × protocolMode → Guide ID 매핑 |
| `AUTO_COMPUTABLE_SLOTS` | 2개 (bmi, regionBucket): 파생 슬롯 자동 계산 규칙 |
| `CONDITIONAL_SKIP_RULES` | 7개: 선행 슬롯 값에 따라 질문 건너뛰기 |
| `SYSTEM_MANAGED_SLOTS` | 1개 (protocolMode): 사용자에게 묻지 않는 슬롯 |
| `CHECKITEM_HINTS` | 50+ 항목: 슬롯별 추출/프롬프트 힌트 (한국어) |
| `REGION_BUCKET_MAP` | 16개: 국내 지역명 → S1~S6 매핑 |

#### 분기점 상세 (BRANCHING_RULES)

| 분기점 Step | 조건 변수 | 분기 결과 |
|-------------|-----------|-----------|
| `p1InformSurgery` | bmi (via ruleBodyFatHigh/Low) | STANDARD / LOW-FAT 프로토콜 |
| `p2InformSurgery` | upsellAccept | 흡입 단독 / 흡입+이식 |
| `p2InformInfoB` | transferType | 일반 / 줄기세포 이식 |
| `p4PreCollect` | regionBucket (via ruleRegion*) | STANDARD / SEMI-REMOTE / FULL |
| `p5AskMedical` | breastCancerHistory 등 (via ruleCancer*) | STANDARD / CONDITIONAL / NOT_ALLOWED |

#### 함수

| 함수 | 시그니처 | 설명 |
|------|----------|------|
| `extract_local_id` | `(uri: str) -> str` | URI에서 `#` 또는 `/` 뒤의 로컬 ID 추출 |

---

### 5.2. `state.py` — 세션 상태 관리

> 대화 세션 상태 데이터 클래스 + 저장소 추상화

#### `ConversationState` (dataclass)

| 필드 | 타입 | 설명 |
|------|------|------|
| `session_id` | `str` | 세션 고유 ID |
| `persona_id` | `str \| None` | 할당된 Persona ID |
| `scenario_id` | `str \| None` | 할당된 Scenario ID |
| `current_step_id` | `str \| None` | 현재 Step ID |
| `slots` | `dict[str, Any]` | 수집된 슬롯 값 |
| `prefetch_slots` | `dict[str, Any]` | n+1 Step용 미리 추출된 슬롯 |
| `history` | `list[dict]` | 대화 히스토리 (role, content, timestamp) |
| `step_turn_count` | `int` | 현재 Step 체류 턴 수 |
| `step_history` | `list[str]` | 방문한 Step ID 이력 |
| `persona_disambiguation` | `dict \| None` | Persona 모호성 해소 대기 상태 |
| `created_at` | `str` | 세션 생성 시각 (ISO) |
| `updated_at` | `str` | 마지막 수정 시각 (ISO) |

#### `ConversationState` 메서드

| 메서드 | 시그니처 | 설명 |
|--------|----------|------|
| `get_slot` | `(var_name, default=None) -> Any` | 슬롯 값 조회 |
| `set_slot` | `(var_name, value) -> None` | 슬롯 값 설정 |
| `is_slot_filled` | `(var_name) -> bool` | 슬롯 채워짐 여부 (None, 빈문자열, "null", 빈 컬렉션 제외) |
| `get_filled_slots` | `() -> dict[str, Any]` | 채워진 슬롯들만 반환 |
| `set_prefetch_slot` | `(var_name, value) -> None` | prefetch 슬롯 설정 (n+1 Step용) |
| `promote_prefetch_slots` | `() -> dict[str, Any]` | prefetch → 정식 slots 승격 (Step 전이 시 호출) |
| `add_turn` | `(role, content, metadata=None) -> None` | 대화 턴 추가 |
| `get_recent_history` | `(n=10) -> list[dict]` | 최근 n개 턴 반환 |
| `get_history_as_messages` | `(n=6) -> list[dict]` | OpenAI messages 형식 변환 |
| `move_to_step` | `(step_id) -> None` | 현재 Step 변경 (이력 기록, 턴 카운터 리셋) |
| `increment_step_turn` | `() -> int` | 현재 Step 턴 카운터 증가 |
| `is_started` | `() -> bool` | 시나리오 시작 여부 확인 |
| `to_dict` / `from_dict` | — | 딕셔너리 직렬화/역직렬화 |
| `to_json` / `from_json` | — | JSON 직렬화/역직렬화 |

#### 저장소 클래스

| 클래스 | 설명 |
|--------|------|
| `StateStorage` | 추상 클래스 (`save`, `load`, `exists`, `delete`) |
| `FileStateStorage` | 파일 기반 (`./states/{session_id}.json`) — 기본값 |
| `RedisStateStorage` | Redis 기반 (TTL 24시간) — 선택적 |

#### 유틸리티 함수

| 함수 | 시그니처 | 설명 |
|------|----------|------|
| `get_storage` | `(backend="file", **kwargs) -> StateStorage` | 백엔드 타입별 저장소 인스턴스 팩토리 |

---

### 5.3. `core.py` — 인프라 레이어

> OpenAI LLM, Neo4j 드라이버, Embedding 캐싱, Vector RAG, TTL Ingestion 통합

#### `CoreConfig` (dataclass)

| 필드 | 기본값 | 설명 |
|------|--------|------|
| `openai_api_key` | (필수) | OpenAI API 키 |
| `openai_embedding_model` | `text-embedding-3-small` | 임베딩 모델 |
| `openai_chat_model` | `gpt-4o` | 채팅 모델 |
| `neo4j_uri` | `""` | Neo4j 접속 URI |
| `neo4j_user` | `neo4j` | Neo4j 사용자 |
| `neo4j_password` | `""` | Neo4j 비밀번호 |
| `neo4j_max_connection_pool_size` | `50` | 연결 풀 크기 |
| `neo4j_connection_acquisition_timeout` | `60.0` | 연결 획득 타임아웃 |
| `neo4j_max_connection_lifetime` | `3600` | 최대 연결 수명 |
| `neo4j_connection_timeout` | `30.0` | 연결 타임아웃 |
| `neo4j_keep_alive` | `True` | Keep-alive 활성화 |

| 클래스메서드 | 시그니처 | 설명 |
|-------------|----------|------|
| `from_env` | `(db_mode="aura") -> CoreConfig` | 환경변수에서 설정 로드. `db_mode`에 따라 `NEO4J_AURA_*` 또는 `NEO4J_LOCAL_*` 사용 |

#### `Chunk` (dataclass)

| 필드 | 타입 | 설명 |
|------|------|------|
| `id` | `str` | 노드 ID |
| `content` | `str` | `name: desc` 형태의 텍스트 |
| `metadata` | `dict` | name, category, stepType 등 |
| `score` | `float` | 코사인 유사도 점수 |

#### `Core` 클래스 메서드

| 카테고리 | 메서드 | 시그니처 | 설명 |
|----------|--------|----------|------|
| **초기화** | `__init__` | `(config: CoreConfig)` | OpenAI 클라이언트 + Neo4j 드라이버 + 임베딩 캐시 초기화 |
| | `close` | `() -> None` | Neo4j 드라이버 종료 |
| **임베딩** | `embed` | `(text: str) -> list[float]` | 텍스트 → 벡터 (MD5 해시 LRU 캐시, 최대 1000개) |
| | `embed_async` | `async (text: str) -> list[float]` | 비동기 임베딩 생성 |
| | `clear_embedding_cache` | `() -> None` | 임베딩 캐시 초기화 |
| **벡터 검색** | `vector_search` | `(question, k=5, search_type="surgery", min_score=0.5) -> list[Chunk]` | Neo4j 벡터 인덱스 검색 (min_score 필터링) |
| | `vector_search_combined` | `(question, k=2, min_score=0.5) -> list[Chunk]` | Surgery + Step 동시 검색, 점수 정렬, 중복 제거 |
| | `vector_search_async` | `async (question, k, search_type, min_score) -> list[Chunk]` | 비동기 벡터 검색 |
| | `vector_search_combined_async` | `async (question, k, min_score) -> list[Chunk]` | Surgery + Step 비동기 병렬 검색 |
| **스키마** | `ensure_schema` | `() -> None` | Neo4j constraints + vector index 생성 |
| **Ingestion** | `ingest_documents` | `(ttl_path: str, create_embeddings=True) -> dict` | TTL 파싱 → 노드/관계 생성 + 임베딩 |
| | `_ingest_nodes` | `(session, g, ONT) -> dict` | RDF 타입별 노드 MERGE |
| | `_collect_properties` | `(g, subject, ONT) -> dict` | RDF subject의 속성 수집 |
| | `_ingest_relations` | `(session, g, ONT) -> int` | RDF 관계 → Neo4j 관계 MERGE |
| | `_get_relation_params` | `(rel_type, from_id, to_id) -> dict` | 관계별 쿼리 파라미터 매핑 |
| | `_create_embeddings` | `() -> None` | Surgery/Step 노드 임베딩 일괄 생성 |
| **유틸** | `run_query` | `(query, **params) -> list[dict]` | 임의 Cypher 쿼리 실행 |
| | `health_check` | `() -> dict` | OpenAI + Neo4j 연결 상태 확인 |

---

### 5.4. `flow.py` — 비즈니스 로직 레이어

> 턴 처리, Persona 판별, Step 전이, 분기 평가, 슬롯 추출, 프롬프트 생성

**가장 큰 파일 (~2100 lines)**로 시스템의 핵심 비즈니스 로직을 담당.

#### 데이터 클래스

##### `StepInfo`

| 필드 | 타입 | 설명 |
|------|------|------|
| `id` | `str` | Step ID |
| `desc` | `str` | Step 설명 |
| `step_type` | `str` | `collect`, `ask`, `inform`, `confirm`, `schedule`, `finalize` |
| `check_items` | `list[dict]` | 수집 대상 CheckItem 목록 |
| `guides` | `list[dict]` | 연결된 Guide 목록 |
| `programs` | `list[dict]` | 추천 Program 목록 |
| `reference_slots` | `list[str]` | 참조용 슬롯 ID 목록 |

##### `TransitionResult`

| 필드 | 타입 | 설명 |
|------|------|------|
| `next_step_id` | `str \| None` | 다음 Step ID (None이면 종료 또는 stay) |
| `via` | `str` | `"branching"`, `"to"`, `"leadsTo"`, `"stay"`, `"end"` |
| `debug` | `dict` | 디버그 정보 |
| `protocol_mode` | `str \| None` | 분기에 의해 설정된 protocolMode |

#### `FlowEngine` 클래스 상수

| 상수 | 값/타입 | 설명 |
|------|---------|------|
| `STALE_STEP_THRESHOLD` | `3` | 동일 Step N턴 이상 체류 시 강제 진행 |
| `PERSONA_AMBIGUITY_THRESHOLD` | `1` | 상위 2개 Persona 점수차가 이 값 이하면 disambiguation |
| `PERSONA_KEYWORDS` | `dict[str, list[str]]` | 7개 Persona × 키워드 리스트 (키워드 기반 판별) |
| `PERSONA_SIGNAL_RULES` | `dict[str, list[dict]]` | 5개 Persona × 복합 신호 보너스 규칙 |
| `_P5_REQUIRED_SIGNALS` | `list[str]` | P5(revisionFatigue) 필수 확증 키워드 |
| `PERSONA_DISAMBIGUATION_QUESTIONS` | `dict[tuple, str]` | Persona 쌍별 확인 질문 |
| `DEFAULT_DISAMBIGUATION_QUESTION` | `str` | 기본 disambiguation 질문 |

#### `FlowEngine` 메서드 (카테고리별)

##### A. 캐시 관리

| 메서드 | 시그니처 | 설명 |
|--------|----------|------|
| `_is_cache_valid` | `(cache_key: str) -> bool` | TTL(5분) 기반 캐시 유효성 확인 |
| `_set_cache_timestamp` | `(cache_key: str) -> None` | 캐시 타임스탬프 설정 |
| `clear_cache` | `() -> None` | 모든 캐시 초기화 |

##### B. Persona / Scenario 해석

| 메서드 | 시그니처 | 설명 |
|--------|----------|------|
| `get_all_personas` | `() -> list[dict]` | 전체 Persona 목록 (캐시) |
| `get_persona` | `(persona_id: str) -> dict \| None` | 단일 Persona 조회 (캐시) |
| `get_scenario` | `(scenario_id: str) -> dict \| None` | Scenario 조회 (캐시) |
| `resolve_persona_scenario` | `(state, user_text) -> ConversationState` | Persona/Scenario 판별 및 할당. 모호하면 disambiguation 질문 저장 |
| `_score_personas` | `(user_text, personas) -> list[dict]` | 전체 Persona 점수 산출 (키워드 + 복합 신호 + P5 감산) |
| `_infer_persona` | `(user_text, personas) -> str` | 최고 점수 Persona 반환 |

##### C. 자동 계산 / 조건부 스킵

| 메서드 | 시그니처 | 설명 |
|--------|----------|------|
| `auto_compute_slots` | `(state) -> list[str]` | 파생 슬롯 자동 계산 (bmi, regionBucket). 새로 계산된 슬롯명 리스트 반환 |
| `_compute_bmi` | `(state) -> float \| None` | bodyInfo에서 키/체중 파싱 → BMI 계산 (3가지 패턴 지원) |
| `_compute_region_bucket` | `(state) -> str \| None` | residenceCountry + domesticDistrict → S1~S6/ABROAD |
| `should_skip_check_item` | `(var_name, state) -> bool` | CONDITIONAL_SKIP_RULES + SYSTEM_MANAGED_SLOTS 기반 스킵 판정 |

##### D. Step 탐색

| 메서드 | 시그니처 | 설명 |
|--------|----------|------|
| `get_step` | `(step_id: str) -> StepInfo \| None` | Step 정보 조회 (Guide/Program/Reference 포함, 캐시) |
| `_infer_step_type` | `(step_id: str) -> str` | Step ID 접두어로 타입 추론 (collect/ask/inform/confirm/finalize) |
| `_is_auto_transition_step` | `(step_id: str) -> bool` | inform 타입이면 True (사용자 입력 없이 자동 전이) |
| `get_step_checks` | `(step_id: str) -> list[dict]` | Step의 CheckItem 목록 (캐시) |
| `get_scenario_all_checks` | `(scenario_id: str) -> list[dict]` | 시나리오 전체 CheckItem (ASKS_FOR, 캐시) |

##### E. Step 전이

| 메서드 | 시그니처 | 설명 |
|--------|----------|------|
| `next_step` | `(state) -> TransitionResult` | 다음 Step 결정 (4단계 평가: BRANCHING → TO → leadsTo → end) |
| `_are_step_checks_filled` | `(step_id, state) -> bool` | Step의 필수 CheckItem 전부 수집 확인 |
| `_get_to_steps` | `(step_id: str) -> list[dict]` | TO 관계로 연결된 다음 Step 목록 |
| `_get_leads_to` | `(step_id: str) -> str \| None` | leadsTo 관계 다음 Step (레거시) |
| `_chain_through_empty_steps` | `(state) -> list[str]` | inform 등 빈 스텝 연쇄 건너뛰기 (최대 5회). 건너뛴 step ID 반환 |
| `_build_skipped_inform_context` | `(skipped_steps, state) -> str` | 건너뛴 inform의 Guide/Program 안내 텍스트 생성 |
| `_handle_stale_step` | `(state) -> None` | 3턴 교착 시 미수집 CheckItem → '미응답' 처리 (confirm/finalize 제외) |

##### F. 분기 평가

| 메서드 | 시그니처 | 설명 |
|--------|----------|------|
| `_evaluate_branching_rules` | `(step_id, state) -> TransitionResult \| None` | BRANCHING_RULES 정적 분기 평가 (priority DESC 정렬) |
| `_determine_protocol_mode` | `(rule, state) -> str \| None` | 분기 규칙 → protocolMode 결정 |
| `_check_has_considers` | `() -> bool` | DB에 CONSIDERS 관계 존재 여부 (1회 캐시) |
| `_load_conditions_via_considers` | `(rule_id) -> list[dict] \| None` | CONSIDERS 관계로 Condition 로드 |
| `_evaluate_rule_filtered` | `(rule_id, state) -> bool` | 3-tier fallback 평가: CONSIDERS → RULE_CONDITION_MAP → WHEN legacy |
| `_load_conditions` | `(condition_ids) -> list[dict]` | Condition 노드 로드 (캐시) |
| `_evaluate_rule_from_db` | `(rule_id, state) -> bool` | WHEN → ConditionGroup 레거시 평가 |
| `_evaluate_condition` | `(condition, state) -> bool` | 단일 Condition 평가 (input/op/ref + missingPolicy) |
| `_compare_values` | `(actual, op, ref, ref_type) -> bool` | 값 비교: number/boolean/string 타입별 연산 |

##### G. Guide 선택

| 메서드 | 시그니처 | 설명 |
|--------|----------|------|
| `select_guides` | `(step_id, state, all_guides) -> list[dict]` | GUIDE_SELECTION_RULES로 protocolMode별 Guide 필터링 |

##### H. Slot 추출

| 메서드 | 시그니처 | 설명 |
|--------|----------|------|
| `extract_slots` | `(state, user_text, step_id=None) -> ConversationState` | LLM으로 현재+n+1 Step CheckItem 값 추출. n+1은 prefetch_slots에 분리 저장 |
| `_build_variable_desc` | `(ci, state) -> str \| None` | CheckItem → LLM 추출 프롬프트용 설명. AUTO/SYSTEM/SKIP 대상은 None |
| `_get_checkitem_options` | `(check_item_id: str) -> list[dict]` | CheckItem의 Option(열거값) 목록 조회 |

##### I. 프롬프트 생성

| 메서드 | 시그니처 | 설명 |
|--------|----------|------|
| `build_step_prompt` | `(step_id, state, rag_context="") -> str` | Step 유형별 시스템 프롬프트 분기 생성 |
| `_build_persona_context` | `(state) -> str` | 페르소나 + 시나리오 컨텍스트 문자열 |
| `_get_guide_text` | `(step, state) -> str` | 선택된 Guide 텍스트 (500자 제한) |
| `_get_program_text` | `(step) -> str` | Program 추천 텍스트 |
| `_build_collect_prompt` | `(step, state, rag) -> str` | collect/ask 타입: 미수집 항목 질문 프롬프트 |
| `_build_inform_prompt` | `(step, state, rag) -> str` | inform 타입: 맞춤 안내 프롬프트 |
| `_build_confirm_prompt` | `(step, state, rag) -> str` | confirm 타입: 수집 정보 확인 프롬프트 |
| `_build_schedule_prompt` | `(step, state, rag) -> str` | schedule 타입: 일정 조율 프롬프트 |
| `_build_finalize_prompt` | `(step, state, rag) -> str` | finalize 타입: 상담 마무리 프롬프트 |
| `_build_default_prompt` | `(step, state, rag) -> str` | 기본 프롬프트 |

##### J. 턴 처리 (Full Turn)

| 메서드 | 시그니처 | 설명 |
|--------|----------|------|
| `process_turn` | `(state, user_text, core=None) -> tuple[str, ConversationState]` | 동기 턴 처리 (slot추출 ∥ RAG검색 병렬) |
| `process_turn_streaming` | `(state, user_text, core=None) -> Generator` | 스트리밍 턴 처리 (청크 단위 yield) |
| `process_turn_async` | `async (state, user_text, core=None) -> tuple[str, ConversationState]` | 비동기 턴 처리 |
| `_generate_response` | `(system_prompt, history) -> str` | LLM 동기 응답 생성 |
| `_generate_response_streaming` | `(system_prompt, history) -> Generator[str]` | LLM 스트리밍 응답 생성 |
| `_generate_response_async` | `async (system_prompt, history) -> str` | LLM 비동기 응답 생성 |

---

### 5.5. `cli.py` — 명령줄 인터페이스

> 개발/운영용 CLI. `python -m cli <command>` 형태로 실행.

#### 헬퍼 함수

| 함수 | 시그니처 | 설명 |
|------|----------|------|
| `get_core` | `(db_mode="aura") -> Core` | Core 인스턴스 팩토리 |
| `get_flow_engine` | `(core, fast_mode=False, model_override=None) -> FlowEngine` | FlowEngine 인스턴스 팩토리 |
| `get_state_storage` | `() -> StateStorage` | StateStorage 인스턴스 팩토리 (환경변수 기반) |

#### 상수

```python
MODEL_PRESETS = {
    "gpt-4o":  {"chat": "gpt-4o",  "slot": "gpt-4o-mini"},
    "gpt-5":   {"chat": "gpt-5",   "slot": "gpt-5-mini"},
}
```

#### CLI Commands (8개)

| 명령어 | 함수 | 설명 |
|--------|------|------|
| `setup-schema` | `cmd_setup_schema` | Neo4j constraints + vector index 생성 |
| `ingest <ttl_path>` | `cmd_ingest` | TTL 파일 → Neo4j 적재 (`--no-embeddings` 옵션) |
| `turn <session_id> <user_text>` | `cmd_turn` | 단일 턴 실행 (테스트용) |
| `repl [session_id]` | `cmd_repl` | 대화형 REPL (`--no-streaming`, `--fast` 옵션) |
| `repl-async [session_id]` | `cmd_repl_async` | 비동기 REPL |
| `health` | `cmd_health` | OpenAI + Neo4j 연결 상태 확인 |
| `query <cypher>` | `cmd_query` | Cypher 쿼리 직접 실행 (디버그) |
| `sessions` | `cmd_list_sessions` | 저장된 세션 목록 조회 |

#### 공통 옵션

| 옵션 | 값 | 설명 |
|------|---|------|
| `--db` | `aura` \| `local` | Neo4j DB 모드 (기본: `aura`) |
| `--model` | `gpt-4o` \| `gpt-5` | LLM 모델 프리셋 |

#### REPL 디버그 커맨드

| 커맨드 | 설명 |
|--------|------|
| `/state` | 현재 persona, scenario, step, slots 표시 |
| `/reset` | 세션 초기화 |
| `/cache` | 캐시 상태 표시 |
| `/clear-cache` | 전체 캐시 초기화 |

---

### 5.6. `patch_graph.py` — Neo4j 그래프 패치 스크립트

> 일회성 그래프 마이그레이션 스크립트. 기존 그래프의 구조적 문제를 수정.

#### 패치 목록

| 패치 상수 | Cypher 수 | 설명 |
|-----------|-----------|------|
| `PATCH_PERSONAL_INFO` | 10 | P1/P3/P4/P5 마무리 Step에 customerName, phoneNumber CheckItem 추가 |
| `PATCH_P5_SPLIT` | 8 | p5AskDetail 과밀 분리: 분기용 3개만 유지, 나머지 4개는 p5AskMedical로 이동. 흐름 재연결 |
| `PATCH_CONSIDERS` | 4 | CONSIDERS 관계 누락 보완: ruleCancerConditional/NotAllowed + ruleImplantIntact/Damaged |

#### 함수

| 함수 | 시그니처 | 설명 |
|------|----------|------|
| `get_driver` | `(db_mode: str) -> Driver` | Neo4j 드라이버 생성 (환경변수 기반) |
| `run_patches` | `(driver, patches, label, dry_run=False) -> None` | 패치 쿼리 목록 실행 (변경 통계 출력) |
| `verify_patch` | `(driver) -> None` | 패치 결과 검증 (12개 검증 쿼리) |
| `main` | `() -> None` | CLI 진입점 (`--db`, `--dry-run` 옵션) |

---

### 5.7. `__init__.py` — 패키지 초기화

```python
__version__ = "0.1.0"
__all__ = ["ConversationState", "Core", "FlowEngine", "__version__"]
```

---

## 6. Neo4j Graph Structure

```
(Persona)──[:HAS_SCENARIO]──>(Scenario)──[:ASKS_FOR]──>(CheckItem)
                                │
                    ┌───(incoming TO 없는 Step = 시작)
                    │
                    ▼
                 (Step)──[:TO]──>(Step)──[:TO]──>...
                    │       │        │
            [:CHECKS]   [:GUIDED_BY]   [:REFERENCE]
                    │       │              │
                    ▼       ▼              ▼
              (CheckItem) (Guide)    (CheckItem)
                    │
              [:HAS_OPTION]──>(Option)

                 (Step)──[:RECOMMENDS]──>(Program)──[:HAS_SIDE_EFFECT]──>(SideEffect)

(Transition)──[:GUARDED_BY]──>(DecisionRule)──[:CONSIDERS]──>(Condition)
                                             └──[:WHEN]──>(ConditionGroup)──[:HAS_CONDITION]──>(Condition)

(Surgery)──[:causeSideEffect]──>(SideEffect)
```

### Node Types (14개)

| 노드 | 주요 속성 | 설명 |
|------|-----------|------|
| `Persona` | id, name, description, tags | 상담 페르소나 (5+2) |
| `Scenario` | id, name, desc, domain, stage_model | 상담 시나리오 |
| `Step` | id, desc, type | 상담 단계 (collect/ask/inform/confirm/finalize) |
| `CheckItem` | id, name, dataType | 수집 대상 정보 항목 |
| `Guide` | id, desc | 상담 가이드 문구 |
| `Program` | id, name, category | 추천 시술 프로그램 |
| `Option` | id, value, desc | CheckItem의 선택지 |
| `Surgery` | id, name, desc, category | 수술 종류 (벡터 검색용) |
| `SideEffect` | id, name, desc | 부작용 |
| `Transition` | id, desc, priority, isDefault | Step 간 전이 메타 |
| `DecisionRule` | id, desc | 분기 조건 규칙 |
| `ConditionGroup` | id | 조건 그룹 (AND/OR) |
| `Condition` | id, input, op, ref, refType, missingPolicy | 단일 비교 조건 |
| `Threshold` | id, name, value | 비교 임계값 |

### Relationship Types (15개)

| 관계 | From → To | 설명 |
|------|-----------|------|
| `HAS_SCENARIO` | Persona → Scenario | 페르소나 소유 시나리오 |
| `HAS_STEP` | Scenario → Step | 시나리오 소속 Step |
| `TO` | Step → Step | Step 순차 흐름 (기본) |
| `CHECKS` | Step → CheckItem | Step에서 수집할 항목 |
| `ASKS_FOR` | Scenario → CheckItem | 시나리오 전체 수집 항목 |
| `GUIDED_BY` | Step → Guide | Step의 가이드 문구 |
| `RECOMMENDS` | Step → Program | Step의 추천 프로그램 |
| `REFERENCE` | Step → CheckItem | 참조용 슬롯 |
| `HAS_OPTION` | CheckItem → Option | CheckItem의 선택지 |
| `HAS_SIDE_EFFECT` | Program → SideEffect | 프로그램의 부작용 |
| `causeSideEffect` | Surgery → SideEffect | 수술의 부작용 |
| `GUARDED_BY` | Transition → DecisionRule | 전이 조건 |
| `CONSIDERS` | DecisionRule → Condition | 규칙의 조건 (권장, 1:N) |
| `WHEN` | DecisionRule → ConditionGroup | 규칙의 조건 그룹 (레거시) |
| `HAS_CONDITION` | ConditionGroup → Condition | 그룹의 조건 |

---

## 7. Personas (7개)

| ID | 이름 | 설명 |
|----|------|------|
| `slimBody` | 슬림바디 | 마른 체형, 지방이식 관심, BMI 기반 분기 |
| `lipoCustomer` | 지방흡입고객 | 지방흡입+이식, upsell 분기, 줄기세포 선택 |
| `skinTreatment` | 피부시술 | 피부 관리, 보톡스/필러, 레이저 |
| `longDistance` | 원거리고객 | 해외/지방 거주, 거주지 기반 프로토콜 분기 |
| `revisionFatigue` | 재수술피로 | 재수술, 보형물 제거/교체, 유방암 분기 |
| `P1_BreastConsult` | 가슴상담 | 레거시 (가슴 관련 범용) |
| `P2_FaceConsult` | 얼굴상담 | 레거시 (얼굴 관련 범용) |

---

## 8. Optimization Strategies

| 전략 | 위치 | 설명 |
|------|------|------|
| 1. 메모리 캐싱 | flow.py | Step, Persona, Scenario, CheckItem 캐시 (TTL 5분) |
| 2. 임베딩 캐싱 | core.py | MD5 해시 기반 LRU 캐시 (최대 1000개) |
| 4. 비동기 처리 | core.py, flow.py | AsyncOpenAI, asyncio.to_thread (RAG + slot 추출 병렬) |
| 5. Neo4j 연결 풀 | core.py | 최대 50개 연결, keep_alive, 타임아웃 설정 |
| 6. LLM 스트리밍 | flow.py | SSE 스트리밍 응답 (REPL 실시간 출력) |
| 7. Vector Search 최적화 | core.py | min_score 필터링, Surgery+Step 합산 정렬 |
| 8. 프롬프트 최적화 | flow.py | 히스토리 6턴 제한, 가이드 500자 제한 |
| 12. LLM 호출 제거 | flow.py | Persona 판별을 키워드+복합신호 기반으로 (LLM 미사용) |
| 15. 병렬 실행 | flow.py | ThreadPoolExecutor로 slot 추출 ∥ RAG 검색 동시 |
| 16. 자동 계산 | flow.py | BMI, regionBucket 파생 슬롯 자동 산출 |

---

## 9. Environment Variables

```bash
# OpenAI
OPENAI_API_KEY=sk-...
OPENAI_EMBEDDING_MODEL=text-embedding-3-small    # 임베딩 모델
OPENAI_CHAT_MODEL=gpt-4o                         # 기본 채팅 모델
SLOT_EXTRACTION_MODEL=gpt-4o-mini                # 슬롯 추출 전용 (선택)

# Neo4j AuraDB
NEO4J_AURA_URI=neo4j+s://xxxxx.databases.neo4j.io
NEO4J_AURA_USER=neo4j
NEO4J_AURA_PASSWORD=...

# Neo4j Local
NEO4J_LOCAL_URI=bolt://localhost:7687
NEO4J_LOCAL_USER=neo4j
NEO4J_LOCAL_PASSWORD=password

# State Storage
STATE_BACKEND=file                                # file | redis
STATE_STORAGE_DIR=./states
REDIS_URL=redis://localhost:6379                  # redis 백엔드 시 필요

# Performance
MAX_RESPONSE_TOKENS=500                           # LLM 최대 응답 토큰
```
