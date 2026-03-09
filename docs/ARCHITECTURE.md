# SC301 Graph RAG Chatbot - Code Specification

> **Date:** 2026-03-07
> **Version:** v5 (Hybrid RAG, config/schema 분리, factories.py 추출)

---

## 1. Architecture Overview

SC301은 **Hybrid RAG 기반 성형외과 상담 챗봇**으로, Neo4j 그래프 DB에 저장된 온톨로지(Persona → Scenario → Step)를 따라가며 사용자와 대화를 진행하고, 지식인 Q&A 벡터 스토어로 일반 질문에도 대응하는 시스템이다.

### 핵심 설계 원칙

- **Graph-Driven Flow**: 대화 흐름이 하드코딩이 아닌 Neo4j 그래프의 Step → Step 관계로 정의됨
- **Hybrid RAG**: GraphRAG(Neo4j 벡터 검색) + QA 벡터 스토어(data/ 165K 문서)를 의도 분류 기반으로 결합
- **Slot-Based State Management**: 각 Step에서 수집해야 할 정보(CheckItem)를 slot으로 관리, 모두 수집 시 다음 Step으로 전이
- **LLM-Powered Extraction + Generation**: OpenAI LLM이 사용자 발화에서 slot 값을 추출하고, 상황에 맞는 응답을 생성
- **Static Routing Table**: 분기 로직은 DB의 Transition/DecisionRule 노드 대신 Python dict(`BRANCHING_RULES`)로 관리하여 성능과 디버깅 편의성 확보
- **Dual Persona Layer**: Flow 페르소나(시나리오 라우팅)와 상담 페르소나(톤/전략)를 이원 구조로 분리

### 레이어 구조

```
+-------------------------------------------------------------+
|  CLI Layer (cli.py)                                          |
|  - argparse 기반 명령행 진입점                                |
|  - REPL(동기/비동기/스트리밍), 단일 턴, 디버그 커맨드          |
+-------------------------------------------------------------+
|  Business Logic Layer (flow/ 패키지)                          |
|  - FlowEngine: Mixin 기반 턴 처리 파이프라인                  |
|  - engine.py: Mixin 조합 + 캐시 관리                         |
|  - persona.py: Persona 판별 (키워드 + 복합신호)               |
|  - navigation.py: Step 전이 + 분기 평가                       |
|  - slots.py: Slot 추출 (LLM) + 자동 계산 + 조건부 스킵        |
|  - consultation.py: 상담 Persona 스코어링                     |
|  - rag_intent.py: Hybrid RAG 의도 분류 + 컨텍스트 조합        |
|  - prompt.py: Step 유형별 시스템 프롬프트 빌더                 |
|  - turn.py: process_turn (동기/스트리밍/비동기) 오케스트레이션  |
+-------------------------------------------------------------+
|  RAG Layer (rag/store.py)                                     |
|  - QAVectorStore: FAISS 기반 인메모리 벡터 스토어              |
|  - FAISS IndexFlatIP 벡터 검색                                |
|  - pickle 캐시 (data/rag_cache.pkl)                           |
+-------------------------------------------------------------+
|  State Layer (state.py)                                       |
|  - ConversationState: 세션 상태 데이터 클래스                  |
|  - Slot 관리, Prefetch, History, 직렬화                       |
|  - Storage: File / Redis 추상화                               |
+-------------------------------------------------------------+
|  Infrastructure Layer (core.py)                               |
|  - OpenAI 클라이언트 (동기/비동기)                             |
|  - Neo4j 드라이버 (연결 풀 최적화)                             |
|  - Embedding (MD5 LRU 캐시)                                   |
|  - GraphRAG Vector Search (Surgery + Step, min_score 필터)    |
|  - Q&A 벡터 스토어 초기화 + 검색 (init_qa_store / qa_search)  |
|  - TTL Ingestion (RDF -> Neo4j 노드/관계)                     |
+-------------------------------------------------------------+
|  Config Layer (config/ 패키지)                                |
|  - branching.py: 정적 라우팅 테이블 (BRANCHING_RULES 등)      |
|  - slots.py: CheckItem 힌트, 자동 계산, 조건부 스킵            |
|  - consultation.py: 상담 키워드/톤/전략 데이터                  |
|  - guides.py: Guide 선택 규칙                                  |
|  - conditions.py: RULE_CONDITION_MAP, OR_LOGIC_RULES          |
+-------------------------------------------------------------+
|  Schema Layer (schema/ 패키지)                                |
|  - queries.py: Cypher 쿼리 상수 65+ 개                        |
|  - ingestion.py: TTL Ingestion 관련 Cypher 쿼리               |
+-------------------------------------------------------------+
     |                    |                    |
  Neo4j DB           OpenAI API        data/ (JSONL+NPZ)
(그래프 온톨로지)    (임베딩/채팅)      (165K Q&A 벡터 스토어)
```

---

## 2. Main Workflow (턴 처리 파이프라인)

사용자의 한 마디(턴) 입력부터 응답 생성까지의 전체 흐름. `flow/turn.py`의 `TurnMixin._prepare_turn()` + `process_turn()` 메서드가 오케스트레이션한다.

```
User Input
    |
    v
+--------------------------------------------------------------+
| 1. state.add_turn("user", text)                               |
|    사용자 입력을 대화 히스토리에 기록                           |
+--------------------------------------------------------------+
| 2. flow.resolve_persona_scenario(state, text)                 |
|    +-- 첫 턴: 키워드+복합신호 기반 Persona 판별                |
|    |   -> 모호하면 disambiguation 질문 반환 (턴 종료)          |
|    |   -> 명확하면 Persona -> Scenario -> 시작 Step 할당       |
|    +-- 2턴째(disambiguation 해소): 원본+답변 합산으로 재분류   |
|    +-- 이미 시작됨: 스킵                                      |
+--------------------------------------------------------------+
| 3. 병렬 실행 (ThreadPoolExecutor)                              |
|    +-- flow.extract_slots(state, text)                        |
|    |   현재 Step의 CheckItem 값을 LLM으로 추출                 |
|    |   + n+1 Step prefetch (비분기 시)                         |
|    |                                                          |
|    +-- core.vector_search_combined(text)  [GraphRAG 검색]     |
|    |   Surgery + Step 벡터 검색                                |
|    |                                                          |
|    +-- core.qa_search(text)  [QA 검색]                        |
|        data/ Q&A 벡터 스토어 검색 (165K 문서)                |
+--------------------------------------------------------------+
| 3.5. flow.auto_compute_slots(state)                           |
|      bmi, regionBucket 등 파생 슬롯 자동 계산                  |
+--------------------------------------------------------------+
| 3.55. flow.score_consultation_persona(state, text)            |
|       상담 Persona 스코어링 (desire/body/social/service)       |
|       -> 누적 점수가 threshold(6.0) 초과 시 톤 확정            |
+--------------------------------------------------------------+
| 3.6. Stale step 감지 (동일 Step 3턴 이상 -> 미수집을 '미응답') |
+--------------------------------------------------------------+
| 3.7. Hybrid RAG 의도 분류 + 컨텍스트 조합                      |
|      _classify_user_intent(): slot_data / general_question /  |
|        mixed 분류 (rule / llm / hybrid 모드)                   |
|      _assemble_rag_context(): GraphRAG + QA 컨텍스트를         |
|        의도에 따라 가중치 조합                                  |
|      -> general_question이면 offscript 템플릿 적용             |
+--------------------------------------------------------------+
| 4. flow.next_step(state)                                      |
|    다음 Step 결정 (평가 순서):                                 |
|    (1) 현재 Step의 CheckItem 전부 수집되었는지 확인            |
|       -> 미수집 있으면 "stay" (현재 Step 유지)                 |
|    (2) BRANCHING_RULES 조건 평가 -> 분기                      |
|       -> protocolMode 설정 (STANDARD/LOW-FAT/FULL 등)         |
|    (3) TO 관계 -> 단일/다중 경로                               |
|    (4) leadsTo 레거시 fallback                                 |
|    (5) None -> 시나리오 종료                                   |
|                                                               |
|    state.move_to_step() + prefetch_slots 승격                  |
+--------------------------------------------------------------+
| 4.5. flow._chain_through_empty_steps(state)                   |
|      inform 스텝 등 CheckItem 없는 스텝 연쇄 건너뛰기          |
|      (최대 5회, 무한루프 방지)                                  |
|      -> 건너뛴 inform의 Guide/Program 안내 내용 수집           |
+--------------------------------------------------------------+
| 6. flow.build_step_prompt(step_id, state, rag_context)        |
|    Step 유형별 시스템 프롬프트 생성                             |
|    + 건너뛴 inform 안내 내용을 프롬프트 앞에 삽입               |
|    + 상담 Persona 톤 지침 주입 (확정된 경우)                    |
+--------------------------------------------------------------+
| 7. LLM 응답 생성 (streaming / blocking / async)               |
|    system_prompt + history(최근 6턴) -> OpenAI ChatCompletion  |
+--------------------------------------------------------------+
| 8. state.add_turn("assistant", response)                      |
|    state 저장 (FileStorage / Redis)                            |
+--------------------------------------------------------------+
    |
    v
Bot Response
```

### 2.1. Persona 판별 워크플로우

```
첫 턴 사용자 입력
    |
    v
_score_personas(): 7개 Persona별 점수 산출
    |  +-- 키워드 매칭 (PERSONA_KEYWORDS)
    |  +-- 복합 신호 보너스 (PERSONA_SIGNAL_RULES)
    |  +-- P5 필수 확증 검사 (재수술 키워드 없으면 감산)
    |
    v
상위 2개 Persona 점수차 비교
    |
    +-- 점수차 > AMBIGUITY_THRESHOLD(1) -> 1위 Persona 확정
    |       -> Persona -> Scenario -> 시작 Step 할당
    |
    +-- 점수차 <= 1 -> disambiguation 질문 반환
            -> persona_disambiguation에 candidates + question 저장
            -> 다음 턴에서 원본+답변 합산 텍스트로 재분류
```

### 2.2. Step 전이 워크플로우

```
현재 Step
    |
    v
CheckItem 수집 완료 확인
    |
    +-- 미수집 항목 있음 -> "stay" (현재 Step 유지, 질문 계속)
    |
    +-- 전부 수집 완료
         |
         +-- BRANCHING_RULES에 있는 Step?
         |       |
         |       +-- Yes -> 조건 평가 (priority DESC)
         |       |         |
         |       |         +-- DecisionRule 기반 (3-tier fallback)
         |       |         |   (1) CONSIDERS 관계 (DB)
         |       |         |   (2) RULE_CONDITION_MAP (하드코딩)
         |       |         |   (3) WHEN -> ConditionGroup (레거시)
         |       |         |
         |       |         +-- 직접 조건 (conditionVar 지정)
         |       |         |
         |       |         +-- Default transition (isDefault=True)
         |       |
         |       |     -> protocolMode 설정 (분기 결과에 따라)
         |       |
         |       +-- No -> TO 관계 follow
         |               |
         |               +-- 1개 -> 그대로 이동
         |               +-- 다중 -> 첫 번째로 이동
         |
         +-- TO도 없으면 -> leadsTo fallback -> 없으면 "end"

이동 후 -> _chain_through_empty_steps()
         -> inform 스텝은 자동 통과 (Guide/Program 안내 수집)
```

### 2.3. Hybrid RAG 의도 분류 워크플로우

Hybrid RAG는 GraphRAG(Neo4j)와 QA 벡터 스토어(data/)를 의도 기반으로 결합한다.

```
사용자 발화
    |
    +-- [병렬] GraphRAG 검색 (Neo4j 벡터 인덱스)
    +-- [병렬] QA 검색 (data/ 165K 문서, FAISS)
    |
    v
_classify_user_intent(user_text, extracted_slot_count, qa_top_score)
    |
    +-- intent_mode = "rule":
    |     질문 마커 + 슬롯 데이터 여부 + QA 점수로 판별
    |
    +-- intent_mode = "llm":
    |     gpt-4o-mini로 3-class 분류
    |
    +-- intent_mode = "hybrid" (기본):
    |     rule 우선 -> uncertain이면 LLM fallback
    |
    v
의도 분류 결과:
    +-- "slot_data":         GraphRAG 우선 + QA 보충 (>0.55)
    +-- "general_question":  QA 우선 + GraphRAG 보충
    +-- "mixed":             둘 다 포함
    |
    v
_assemble_rag_context(): 의도별 가중치로 컨텍스트 조합
    -> general_question이면 _OFFSCRIPT_TEMPLATE 적용
       (QA 기반 답변 + 현재 Step 질문 복귀)
```

### 2.4. 상담 Persona 스코어링 워크플로우 (톤/전략 레이어)

Flow 페르소나(시나리오 라우팅)와 독립적으로 동작하는 톤/전략 결정 시스템.
4차원: desire(감정·심리), body(신체·건강), social(타인·이미지), service(서비스·효율)

```
매 턴 사용자 입력
    |
    v
consultation_scoring_mode 확인
    |
    +-- "off" -> 스킵
    +-- "hybrid" (기본)
    |       |
    |       +-- Rule 기반 스코어 (키워드 + 주어 패턴)
    |       |   -> 신호 합계 >= 2.0 -> rule 스코어 사용
    |       |   -> 신호 합계 < 2.0 -> LLM 스코어 fallback
    |       |
    |       +-- 추천질문 매칭 보너스 (+3.0)
    |
    +-- "llm" -> LLM-as-Judge (gpt-4o-mini, 4차원 0~3점)

스코어 누적 -> threshold(6.0) 초과 시 상담 Persona 확정
    -> _build_persona_context()에서 톤 지침 주입
       (strategy, trigger_expressions, guide_tone, taboo)
```

---

## 3. Module Dependency

```
             +----------+
             |  cli.py  |  <- 진입점 (argparse CLI)
             +----+-----+
                  |
        +---------+-----------+
        v         v           v
   +---------+ +---------+ +----------+
   | core.py | | flow/   | | state.py |
   | (인프라) | |(비즈니스)| | (상태)   |
   +----+----+ +----+----+ +----------+
        |           |          ^
        |           +----------+ (flow가 state를 조작)
        |           |
        v           v
   +------------------+
   |    schema/        |  <- Cypher 쿼리
   +------------------+
   +------------------+
   |    config/        |  <- 정적 라우팅 테이블 + 상담 키워드/톤 전략
   +------------------+

   +------------------+
   |  rag/store.py    |  <- Q&A 벡터 스토어 (core.py에서 사용)
   +------------------+

독립 스크립트:
   +--------------+  +--------------------+  +------------------------+
   | patch_graph.py|  | scripts/export_neo4j|  | jisikin/build_embeddings|
   +--------------+  +--------------------+  +------------------------+
   Neo4j 패치         Neo4j 데이터 내보내기    Q&A 임베딩 재생성

External:
  - OpenAI API (core.py -> embedding/chat, flow/ -> slot추출/응답)
  - Neo4j DB (core.py -> 연결관리, flow/ -> 쿼리 실행)
  - data/ (JSONL+NPZ -> rag/store.py -> core.py)
```

---

## 4. Directory Structure

```
sc301/
+-- __init__.py              # 패키지 초기화 (ConversationState, Core, FlowEngine export)
|
|  -- 코어 모듈 --
+-- cli.py                   # CLI 진입점 (8개 서브커맨드)
+-- core.py                  # Core: OpenAI + Neo4j + Embedding + Vector Search + QA Store
+-- state.py                 # ConversationState + Storage (File/Redis)
+-- rag/
|   +-- __init__.py          # QAVectorStore, QASearchResult export
|   +-- store.py             # QAVectorStore: FAISS 기반 인메모리 벡터 스토어
|
|  -- flow/ 패키지 (비즈니스 로직) --
+-- flow/
|   +-- __init__.py          # FlowEngine, StepInfo, TransitionResult export
|   +-- _types.py            # StepInfo, TransitionResult, TurnContext 데이터 클래스
|   +-- engine.py            # FlowEngine: Mixin 조합 + 캐시 관리
|   +-- persona.py           # PersonaMixin: Persona 판별/Scenario 할당
|   +-- navigation.py        # NavigationMixin: Step 전이, 분기 평가, Guide 선택
|   +-- slots.py             # SlotMixin: LLM 슬롯 추출, 자동 계산, 조건부 스킵
|   +-- consultation.py      # ConsultationMixin: 상담 Persona 스코어링
|   +-- rag_intent.py        # RAGIntentMixin: Hybrid RAG 의도 분류 + 컨텍스트 조합
|   +-- prompt.py            # PromptMixin: Step 유형별 프롬프트 생성
|   +-- turn.py              # TurnMixin: process_turn 오케스트레이션
|
|  -- config/ 패키지 (비즈니스 룰 설정) --
+-- config/
|   +-- __init__.py          # 하위 호환: from config import X 유지
|   +-- branching.py         # BRANCHING_RULES 정적 라우팅 테이블
|   +-- conditions.py        # RULE_CONDITION_MAP, OR_LOGIC_RULES
|   +-- guides.py            # GUIDE_SELECTION_RULES
|   +-- slots.py             # AUTO_COMPUTABLE_SLOTS, CONDITIONAL_SKIP_RULES, CHECKITEM_HINTS 등
|   +-- consultation.py      # 상담 키워드/톤/전략 데이터
|
|  -- schema/ 패키지 (Neo4j 스키마) --
+-- schema/
|   +-- __init__.py          # 하위 호환: from schema import X 유지
|   +-- queries.py           # Cypher 쿼리 상수 (Flow 조회, 벡터 검색 등)
|   +-- ingestion.py         # TTL Ingestion Cypher (노드 Merge, 관계 생성, 임베딩)
|
|  -- data/ (RAG 데이터, gitignore) --
+-- data/
|   +-- rag_docs.jsonl       # 165,009건 Q&A 문서 (네이버 지식인)
|   +-- rag_docs.embeddings.npz  # 사전 계산 임베딩 (text-embedding-3-small, 1536d)
|   +-- rag_cache.pkl        # pickle 캐시
|   +-- sc301_system_prompt3.txt  # 시스템 프롬프트
|
|  -- jisikin/ (개발 참고용) --
+-- jisikin/
|   +-- build_embeddings.py  # 임베딩 재생성 스크립트 (OpenAI API)
|
|  -- 그래프 유지보수 --
+-- patch_graph.py           # Neo4j 그래프 패치 스크립트 (3 패치셋)
|
+-- scripts/
|   +-- export_neo4j.py      # Neo4j 데이터를 Cypher 텍스트로 내보내기
|   +-- encrypt_env.sh       # .env 암호화
|   +-- decrypt_env.sh       # .env 복호화
|   +-- setup_server.sh      # 서버 초기 세팅
|   +-- import_neo4j.sh      # Cypher 파일로 Neo4j 데이터 임포트
|
|  -- 테스트 / 벤치마크 --
+-- test_scenarios.py        # 단위/통합 테스트
+-- test_repl.py             # REPL 시뮬레이션 테스트
+-- test_persona_identification.py  # Persona 판별 테스트
+-- benchmark_scenarios.py   # 성능 벤치마크
|
|  -- 설정 / 데이터 --
+-- requirements.txt         # Python 의존성
+-- .env                     # 환경변수 (API 키, DB 접속 정보)
+-- states/                  # 세션 상태 JSON 파일 저장 디렉토리
+-- backups/                 # Neo4j 데이터 내보내기 파일 저장
|
|  -- 문서 --
+-- README.md                # 프로젝트 개요 (GitHub 랜딩 페이지)
+-- GRAPH_RAG_SPEC.md        # Graph RAG 전체 스펙 문서
+-- docs/
|   +-- ARCHITECTURE.md      # 코드 아키텍처 명세 (본 문서)
|   +-- SETUP.md             # 환경 설정 가이드
|   +-- TESTING.md           # 테스트 시나리오 가이드
```

---

## 5. File-by-File Specification

### 5.1. `schema/` + `config/` — Neo4j 스키마 & 비즈니스 룰 패키지

> 기존 `schema.py` 단일 파일을 schema/(Cypher 쿼리)와 config/(비즈니스 룰)로 분리. `from schema import X`, `from config import X` 하위 호환 유지.

#### 모듈 구성

| 모듈 | 주요 상수 | 설명 |
|------|-----------|------|
| `schema/queries.py` | `QUERY_ALL_PERSONAS`, `QUERY_VECTOR_SEARCH_*` 등 | Cypher 쿼리 상수 (Flow 조회 13종, 벡터 검색 2종) |
| `schema/ingestion.py` | `SCHEMA_QUERIES`, `VECTOR_INDEX_QUERIES`, `QUERY_MERGE_*`, `QUERY_CREATE_REL_*` | 스키마 생성, 노드 Merge 14종, 관계 생성 18종, 임베딩 업데이트 |
| `config/branching.py` | `BRANCHING_RULES` | 5개 분기점 × 총 16개 규칙 |
| `config/conditions.py` | `RULE_CONDITION_MAP`, `OR_LOGIC_RULES` | DecisionRule → Condition 매핑, OR 로직 규칙 |
| `config/guides.py` | `GUIDE_SELECTION_RULES` | 9개 Step × protocolMode → Guide ID 매핑 |
| `config/slots.py` | `AUTO_COMPUTABLE_SLOTS`, `CONDITIONAL_SKIP_RULES`, `SYSTEM_MANAGED_SLOTS`, `CHECKITEM_HINTS`, `REGION_BUCKET_MAP` | 슬롯 자동 계산, 조건부 스킵, 힌트 50+항목 |
| `config/consultation.py` | `CONSULTATION_KEYWORDS`, `CONSULTATION_TONE_STRATEGIES` 등 | 상담 Persona 4차원 키워드/톤/전략 데이터 |

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
| `persona_id` | `str \| None` | 할당된 Flow Persona ID |
| `scenario_id` | `str \| None` | 할당된 Scenario ID |
| `current_step_id` | `str \| None` | 현재 Step ID |
| `slots` | `dict[str, Any]` | 수집된 슬롯 값 |
| `prefetch_slots` | `dict[str, Any]` | n+1 Step용 미리 추출된 슬롯 |
| `history` | `list[dict]` | 대화 히스토리 (role, content, timestamp) |
| `step_turn_count` | `int` | 현재 Step 체류 턴 수 |
| `step_history` | `list[str]` | 방문한 Step ID 이력 |
| `persona_disambiguation` | `dict \| None` | Persona 모호성 해소 대기 상태 |
| `consultation_persona` | `str \| None` | 확정된 상담 페르소나 (desire/body/social/service) |
| `consultation_scores` | `dict[str, float]` | 4차원 누적 스코어 |
| `consultation_signals` | `list[dict]` | 턴별 스코어링 신호 로그 |
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
| `promote_prefetch_slots` | `() -> dict[str, Any]` | prefetch → 정식 slots 승격 (Step 전이 시 호출). 이미 채워진 슬롯은 덮어쓰지 않음 |
| `add_turn` | `(role, content, metadata=None) -> None` | 대화 턴 추가 |
| `get_recent_history` | `(n=10) -> list[dict]` | 최근 n개 턴 반환 |
| `get_history_as_messages` | `(n=6) -> list[dict]` | OpenAI messages 형식 변환 |
| `move_to_step` | `(step_id) -> None` | 현재 Step 변경 (이력 기록, 턴 카운터 리셋) |
| `increment_step_turn` | `() -> int` | 현재 Step 턴 카운터 증가, 새 카운트 반환 |
| `is_started` | `() -> bool` | 시나리오 시작 여부 확인 (scenario_id && current_step_id 존재) |
| `to_dict` / `from_dict` | — | 딕셔너리 직렬화/역직렬화 |
| `to_json` / `from_json` | — | JSON 직렬화/역직렬화 |
| `_touch` | `() -> None` | updated_at 타임스탬프 갱신 (내부 헬퍼) |

#### 저장소 클래스

| 클래스 | 메서드 | 설명 |
|--------|--------|------|
| `StateStorage` | `save`, `load`, `exists`, `delete` | 추상 클래스 |
| `FileStateStorage` | + `list_sessions` | 파일 기반 (`./states/{session_id}.json`) — 기본값 |
| `RedisStateStorage` | `save(ttl=86400)` | Redis 기반 (TTL 24시간) — 선택적 |

#### 유틸리티 함수

| 함수 | 시그니처 | 설명 |
|------|----------|------|
| `get_storage` | `(backend="file", **kwargs) -> StateStorage` | 백엔드 타입별 저장소 인스턴스 팩토리 |

---

### 5.3. `core.py` — 인프라 레이어

> OpenAI LLM, Neo4j 드라이버, Embedding 캐싱, Vector RAG, Q&A 벡터 스토어, TTL Ingestion 통합

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
| `neo4j_max_connection_lifetime` | `3600` | 최대 연결 수명(초) |
| `neo4j_connection_timeout` | `30.0` | 연결 타임아웃(초) |
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
| **초기화** | `__init__` | `(config: CoreConfig)` | OpenAI 클라이언트(동기+비동기) + Neo4j 드라이버 + 임베딩 캐시 + qa_store=None 초기화 |
| | `close` | `() -> None` | Neo4j 드라이버 종료 |
| | `__enter__` / `__exit__` | — | Context manager 지원 |
| **임베딩 캐시** | `_get_embedding_cache_key` | `(text: str) -> str` | 텍스트의 MD5 해시를 캐시 키로 생성 |
| | `clear_embedding_cache` | `() -> None` | 임베딩 캐시 초기화 |
| **임베딩** | `embed` | `(text: str) -> list[float]` | 텍스트 → 벡터 (MD5 해시 LRU 캐시, 최대 1000개) |
| | `embed_async` | `async (text: str) -> list[float]` | 비동기 임베딩 생성 (캐시 적용) |
| **벡터 검색** | `vector_search` | `(question, k=5, search_type="surgery", min_score=0.5) -> list[Chunk]` | Neo4j 벡터 인덱스 검색 (min_score 필터링) |
| | `vector_search_combined` | `(question, k=2, min_score=0.5) -> list[Chunk]` | Surgery + Step 동시 검색, 점수 정렬, 중복 제거, 상위 k*2개 반환 |
| | `vector_search_async` | `async (question, k, search_type, min_score) -> list[Chunk]` | 비동기 벡터 검색 (asyncio.to_thread 래핑) |
| | `vector_search_combined_async` | `async (question, k, min_score) -> list[Chunk]` | Surgery + Step 비동기 병렬 검색 (asyncio.gather) |
| **Q&A 벡터 스토어** | `init_qa_store` | `(docs_dir=None, cache_path=None) -> None` | data/ JSONL+NPZ 로드. pickle 캐시 우선 (data/rag_cache.pkl) |
| | `qa_search` | `(query, k=3, min_score=0.45) -> list[QASearchResult]` | Q&A 벡터 검색. Core.embed() 캐시 활용 |
| **스키마** | `ensure_schema` | `() -> None` | Neo4j constraints + vector index 생성 |
| **TTL Ingestion** | `ingest_documents` | `(ttl_path: str, create_embeddings=True) -> dict` | TTL 파싱 → 노드/관계 생성 + 임베딩. 처리 통계 반환 |
| | `_ingest_nodes` | `(session, g, ONT) -> dict` | RDF 타입별 노드 MERGE (Persona, Scenario, Step, CheckItem 등 9종) |
| | `_collect_properties` | `(g, subject, ONT) -> dict` | RDF subject의 속성 수집 (known_props 20개 필터) |
| | `_ingest_relations` | `(session, g, ONT) -> int` | RDF 관계 → Neo4j 관계 MERGE (17종 관계 매핑) |
| | `_get_relation_params` | `(rel_type, from_id, to_id) -> dict` | 관계 타입별 쿼리 파라미터 매핑 |
| | `_create_embeddings` | `() -> None` | Surgery/Step/CheckItem 노드 임베딩 일괄 생성 (embedding IS NULL인 것만) |
| **유틸** | `run_query` | `(query, **params) -> list[dict]` | 임의 Cypher 쿼리 실행 |
| | `health_check` | `() -> dict` | OpenAI + Neo4j 연결 상태 확인 + 임베딩 캐시 크기 반환 |

---

### 5.4. `rag/store.py` — Q&A 벡터 스토어

> data/ JSONL+NPZ 기반 FAISS 인메모리 벡터 스토어. Hybrid RAG의 QA 검색 담당.

#### 데이터 클래스

##### `JisikinEntry`

| 필드 | 타입 | 설명 |
|------|------|------|
| `id` | `str` | 문서 ID ("K_0", "K_1", ...) |
| `content` | `str` | "질문: ...\n답변: ..." 형태의 전체 텍스트 |
| `question` | `str` | metadata.question (질문만) |
| `answer` | `str` | metadata.answer (답변만) |

##### `QASearchResult`

| 필드 | 타입 | 설명 |
|------|------|------|
| `entry` | `JisikinEntry` | 검색된 Q&A 항목 |
| `score` | `float` | 코사인 유사도 점수 |

#### `QAVectorStore` 클래스

| 카테고리 | 메서드 | 시그니처 | 설명 |
|----------|--------|----------|------|
| **속성** | `is_ready` | `@property -> bool` | 데이터+임베딩 로드 완료 여부 |
| **로드** | `load_from_jsonl` | `(jsonl_path, npz_path) -> int` | JSONL 문서 로드 + NPZ 사전 임베딩 로드. ID 순서 검증. 로드 건수 반환 |
| | `load_from_cache` | `(cache_path) -> bool` | pickle 캐시 로드. 성공 여부 반환 |
| | `save_cache` | `(cache_path) -> None` | 현재 상태를 pickle 캐시로 저장 |
| **검색** | `search` | `(query_embedding, k=3, min_score=0.45) -> list[QASearchResult]` | 코사인 유사도 기반 검색. 점수 내림차순 반환 |
| **내부** | `_build_norms` | `() -> None` | 임베딩 행렬의 L2 정규화 버전 캐싱 |

#### 로드 흐름

```
1. pickle 캐시 (data/rag_cache.pkl) 시도 -> 성공 시 완료
2. JSONL (rag_docs.jsonl) + NPZ (rag_docs.embeddings.npz) 로드
   -> pickle 캐시 저장 -> 완료
3. NPZ 로드 실패 시 -> JSONL만 로드 (검색 불가, 경고 메시지)
   -> 'python jisikin/build_embeddings.py' 안내
```

---

### 5.5. `flow/` — 비즈니스 로직 레이어 (Mixin 패키지)

> 기존 `flow.py` (~2260 lines)를 7개 Mixin 모듈로 분리. FlowEngine이 모든 Mixin을 다중 상속으로 조합.

#### 패키지 구조

| 모듈 | Mixin | 역할 |
|------|-------|------|
| `engine.py` | `FlowEngine` | Mixin 조합 + `__init__` + 캐시 관리 |
| `_types.py` | — | `StepInfo`, `TransitionResult`, `TurnContext` 데이터 클래스 |
| `persona.py` | `PersonaMixin` | Persona/Scenario 판별, 키워드 매칭, disambiguation |
| `navigation.py` | `NavigationMixin` | Step 전이, 분기 평가, Guide 선택, 빈 스텝 체인 |
| `slots.py` | `SlotMixin` | LLM 슬롯 추출, 자동 계산, 조건부 스킵 |
| `consultation.py` | `ConsultationMixin` | 상담 Persona 4차원 스코어링 |
| `rag_intent.py` | `RAGIntentMixin` | Hybrid RAG 의도 분류 + 컨텍스트 조합 + 검색 헬퍼 |
| `prompt.py` | `PromptMixin` | Step 유형별 시스템 프롬프트 빌더 |
| `turn.py` | `TurnMixin` | process_turn 오케스트레이션 (동기/스트리밍/비동기) |

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

#### `FlowEngine.__init__` 파라미터

| 파라미터 | 타입 | 기본값 | 설명 |
|----------|------|--------|------|
| `driver` | `Driver` | (필수) | Neo4j 드라이버 |
| `openai_client` | `OpenAI \| None` | `None` | 동기 OpenAI 클라이언트 |
| `chat_model` | `str` | `"gpt-4o"` | 응답 생성용 모델 |
| `async_openai_client` | `AsyncOpenAI \| None` | `None` | 비동기 OpenAI 클라이언트 |
| `slot_extraction_model` | `str \| None` | `None` | 슬롯 추출 전용 모델 (미지정 시 chat_model) |
| `max_response_tokens` | `int` | `500` | LLM 최대 응답 토큰 |
| `consultation_scoring_mode` | `str` | `"hybrid"` | 상담 스코어링 모드: `"hybrid"` / `"llm"` / `"off"` |
| `intent_mode` | `str` | `"hybrid"` | Hybrid RAG 의도 분류 모드: `"rule"` / `"llm"` / `"hybrid"` |

#### `FlowEngine` 클래스 상수

| 상수 | 값/타입 | 설명 |
|------|---------|------|
| `STALE_STEP_THRESHOLD` | `3` (모듈 레벨) | 동일 Step N턴 이상 체류 시 강제 진행 |
| `PERSONA_AMBIGUITY_THRESHOLD` | `1` | 상위 2개 Persona 점수차가 이 값 이하면 disambiguation |
| `PERSONA_KEYWORDS` | `dict[str, list[str]]` | 7개 Persona × 키워드 리스트. RED(최우선) 그룹 포함 |
| `PERSONA_SIGNAL_RULES` | `dict[str, list[dict]]` | 5개 Persona × 복합 신호 보너스 규칙 ({signals, bonus}) |
| `_P5_REQUIRED_SIGNALS` | `list[str]` | P5(revisionFatigue) 필수 확증 키워드 14개. 하나도 없으면 -5점 |
| `PERSONA_DISAMBIGUATION_QUESTIONS` | `dict[tuple, str]` | Persona 쌍별 확인 질문 |
| `DEFAULT_DISAMBIGUATION_QUESTION` | `str` | 기본 disambiguation 질문 |

#### Mixin 메서드 (모듈별)

##### A. `engine.py` — 캐시 관리

| 메서드 | 시그니처 | 설명 |
|--------|----------|------|
| `_is_cache_valid` | `(cache_key: str) -> bool` | TTL(5분) 기반 캐시 유효성 확인 |
| `_set_cache_timestamp` | `(cache_key: str) -> None` | 캐시 타임스탬프 설정 |
| `clear_cache` | `() -> None` | 모든 캐시 초기화 (step, persona, scenario, condition, considers) |

##### B. `persona.py` — PersonaMixin

| 메서드 | 시그니처 | 설명 |
|--------|----------|------|
| `get_all_personas` | `() -> list[dict]` | 전체 Persona 목록 (캐시) |
| `get_persona` | `(persona_id: str) -> dict \| None` | 단일 Persona 조회 (캐시) |
| `get_scenario` | `(scenario_id: str) -> dict \| None` | Scenario 조회 (캐시) |
| `resolve_persona_scenario` | `(state, user_text) -> ConversationState` | Persona/Scenario 판별 및 할당. Turn 1: 모호하면 disambiguation 저장. Turn 2: 합산 재분류 |
| `_score_personas` | `(user_text, personas) -> list[dict]` | 전체 Persona 점수 산출 (키워드 매칭 + 복합 신호 보너스 + P5 필수확증 감산). score DESC 정렬 반환 |
| `_infer_persona` | `(user_text, personas) -> str` | 최고 점수 Persona ID 반환. 모든 0점이면 첫 번째 Persona |

##### C. `slots.py` — SlotMixin

| 메서드 | 시그니처 | 설명 |
|--------|----------|------|
| `extract_slots` | `(state, user_text, step_id=None) -> ConversationState` | LLM으로 현재+n+1 Step CheckItem 값 추출. n+1은 prefetch_slots에 분리 저장. 분기점이면 현재 Step만 |
| `_build_variable_desc` | `(ci, state) -> str \| None` | CheckItem → LLM 추출 프롬프트용 설명. AUTO/SYSTEM/SKIP 대상은 None. Option 열거값/CHECKITEM_HINTS 포함 |
| `_get_checkitem_options` | `(check_item_id: str) -> list[dict]` | CheckItem의 Option(열거값) 목록 Neo4j 조회 |
| `auto_compute_slots` | `(state) -> list[str]` | 파생 슬롯 자동 계산. 새로 계산된 슬롯명 리스트 반환 |
| `_compute_bmi` | `(state) -> float \| None` | bodyInfo에서 키/체중 파싱 → BMI 계산. 3가지 패턴: (1) 170cm 65kg (2) 키 170 몸무게 65 (3) 170/65 |
| `_compute_region_bucket` | `(state) -> str \| None` | residenceCountry + domesticDistrict → S1~S6/ABROAD. REGION_BUCKET_MAP 정확/부분 매칭 |
| `should_skip_check_item` | `(var_name, state) -> bool` | SYSTEM_MANAGED_SLOTS + CONDITIONAL_SKIP_RULES 기반 스킵 판정. 선행 정보 없으면 스킵하지 않음 |

##### D. `navigation.py` — NavigationMixin

| 메서드 | 시그니처 | 설명 |
|--------|----------|------|
| `get_step` | `(step_id: str) -> StepInfo \| None` | Step 정보 조회 (Guide/Program/Reference 포함, null 항목 제거, 캐시) |
| `_infer_step_type` | `(step_id: str) -> str` | Step ID 접두어로 타입 추론: collect/ask/inform/confirm/finalize |
| `_is_auto_transition_step` | `(step_id: str) -> bool` | inform 타입이면 True (사용자 입력 없이 자동 전이) |
| `get_step_checks` | `(step_id: str) -> list[dict]` | Step의 CheckItem 목록 (CHECKS 관계, 캐시) |
| `get_scenario_all_checks` | `(scenario_id: str) -> list[dict]` | 시나리오 전체 CheckItem (ASKS_FOR 관계, 캐시) |
| `next_step` | `(state) -> TransitionResult` | 다음 Step 결정. 평가 순서: (1) CheckItem 수집 확인 → (2) BRANCHING → (3) TO → (4) leadsTo → (5) end |
| `_are_step_checks_filled` | `(step_id, state) -> bool` | Step의 필수 CheckItem 전부 수집 확인. 조건부 스킵/시스템관리/자동계산 항목은 "수집된 것"으로 간주 |
| `_get_to_steps` | `(step_id: str) -> list[dict]` | TO 관계로 연결된 다음 Step 목록 |
| `_get_leads_to` | `(step_id: str) -> str \| None` | leadsTo 관계 다음 Step (레거시 호환) |
| `_chain_through_empty_steps` | `(state) -> list[str]` | inform 등 빈 스텝 연쇄 건너뛰기 (최대 5회). 건너뛴 inform step ID 리스트 반환 |
| `_build_skipped_inform_context` | `(skipped_steps, state) -> str` | 건너뛴 inform의 Guide/Program 안내 텍스트 생성. "[반드시 고객에게 설명]" 지시 포함 |
| `_handle_stale_step` | `(state) -> None` | 3턴 교착 시 미수집 CheckItem → '미응답' 처리. confirm/finalize 스텝은 제외 |
| `_evaluate_branching_rules` | `(step_id, state) -> TransitionResult \| None` | BRANCHING_RULES 정적 분기 평가. priority DESC 정렬, default fallback |
| `_determine_protocol_mode` | `(rule, state) -> str \| None` | ruleId → protocolMode 결정 (STANDARD/LOW-FAT/FULL/SEMI-REMOTE/CONDITIONAL/NOT_ALLOWED) |
| `_check_has_considers` | `() -> bool` | DB에 CONSIDERS 관계 존재 여부 확인 (1회 실행 후 캐싱) |
| `_load_conditions_via_considers` | `(rule_id) -> list[dict] \| None` | CONSIDERS 관계로 Condition 로드. 없으면 None (fallback 신호) |
| `_evaluate_rule_filtered` | `(rule_id, state) -> bool` | 3-tier fallback 평가: (1) CONSIDERS → (2) RULE_CONDITION_MAP → (3) WHEN legacy. OR_LOGIC_RULES 적용 |
| `_load_conditions` | `(condition_ids) -> list[dict]` | Condition 노드 로드 (개별 캐시) |
| `_evaluate_rule_from_db` | `(rule_id, state) -> bool` | WHEN → ConditionGroup → HAS_CONDITION 레거시 평가 |
| `_evaluate_condition` | `(condition, state) -> bool` | 단일 Condition 평가 (input/op/ref/refType + missingPolicy: TRUE/FALSE/UNKNOWN) |
| `_compare_values` | `(actual, op, ref, ref_type) -> bool` | 값 비교: number(< <= > >= = !=), boolean(= !=), string(= !=) |
| `select_guides` | `(step_id, state, all_guides) -> list[dict]` | GUIDE_SELECTION_RULES로 protocolMode별 Guide 필터링. 매칭 안되면 전체 반환 |

##### E. `consultation.py` — ConsultationMixin

| 메서드 | 시그니처 | 설명 |
|--------|----------|------|
| `score_consultation_persona` | `(state, user_text) -> None` | 매 턴 상담 Persona 신호 누적. threshold 초과 시 확정. 이미 확정됐으면 스킵 |
| `_rule_score_consultation` | `(user_text) -> dict[str, float]` | Rule 기반: CONSULTATION_KEYWORDS 키워드 매칭(x1.5) + CONSULTATION_SUBJECT_PATTERNS 패턴(x1.0) |
| `_llm_score_consultation` | `(user_text, state) -> dict[str, float]` | LLM-as-Judge: 경량 모델로 4차원 0~3점 JSON 반환 후 x1.5 |
| `_check_recommended_q_match` | `(user_text) -> dict[str, float]` | 추천질문 부분 문자열 매칭 (CONSULTATION_RECOMMENDED_Q_MAP, x3.0) |

##### F. `rag_intent.py` — RAGIntentMixin

| 메서드 | 시그니처 | 설명 |
|--------|----------|------|
| `_classify_user_intent` | `(user_text, extracted_slot_count, qa_top_score) -> str` | 의도 분류 (rule/llm/hybrid 모드). "slot_data" / "general_question" / "mixed" 반환 |
| `_classify_intent_rule` | `(user_text, extracted_slot_count, qa_top_score) -> str` | 규칙 기반: 질문 마커 + 슬롯 데이터 + QA 점수로 분류 |
| `_classify_intent_llm` | `(user_text) -> str` | LLM 기반: gpt-4o-mini로 3-class 분류 |
| `_assemble_rag_context` | `(intent, graph_rag_context, qa_context, qa_score) -> str` | 의도에 따라 GraphRAG + QA 컨텍스트 가중치 조합 |
| `_do_graph_rag_search` | `(core, user_text) -> tuple[str, float]` | GraphRAG 검색 (vector_search_combined, k=2) |
| `_do_qa_search` | `(core, user_text) -> tuple[str, float]` | Q&A 검색 (qa_search, k=3, min_score=0.45) |

##### G. `prompt.py` — PromptMixin

| 메서드 | 시그니처 | 설명 |
|--------|----------|------|
| `build_step_prompt` | `(step_id, state, rag_context="") -> str` | Step 유형별 시스템 프롬프트 분기 생성 (6종 빌더) |
| `_build_persona_context` | `(state) -> str` | 페르소나 + 시나리오 + 상담 톤 지침 컨텍스트 문자열 |
| `_get_guide_text` | `(step, state) -> str` | 선택된 Guide 텍스트 (500자 제한) |
| `_get_program_text` | `(step) -> str` | Program 추천 텍스트 |
| `_build_collect_prompt` | `(step, state, rag) -> str` | collect/ask: 미수집 항목 질문 + 이미 수집된 정보 + Guide |
| `_build_inform_prompt` | `(step, state, rag) -> str` | inform: 수집 정보 기반 맞춤 안내 + Guide + Program |
| `_build_confirm_prompt` | `(step, state, rag) -> str` | confirm: 수집 정보 요약 확인 + 미수집 항목 질문 |
| `_build_schedule_prompt` | `(step, state, rag) -> str` | schedule: 일정 조율 |
| `_build_finalize_prompt` | `(step, state, rag) -> str` | finalize: 상담 마무리 요약 + 다음 단계 안내 |
| `_build_default_prompt` | `(step, state, rag) -> str` | 기본 프롬프트 |

##### H. `turn.py` — TurnMixin

| 메서드 | 시그니처 | 설명 |
|--------|----------|------|
| `process_turn` | `(state, user_text, core=None) -> tuple[str, ConversationState]` | 동기 턴 처리. slot추출 + GraphRAG + QA검색 병렬 (ThreadPoolExecutor) |
| `process_turn_streaming` | `(state, user_text, core=None) -> Generator` | 스트리밍 턴 처리. 청크 단위 yield → 마지막에 (response, state) yield |
| `process_turn_async` | `async (state, user_text, core=None) -> tuple[str, ConversationState]` | 비동기 턴 처리. asyncio.to_thread + async OpenAI |
| `_prepare_turn` | `(state, user_text, core) -> TurnContext` | 턴 준비: 병렬 실행(slot추출+GraphRAG+QA) → 의도 분류 → 컨텍스트 조합 |
| `_generate_response` | `(system_prompt, history) -> str` | LLM 동기 응답 생성 (max_completion_tokens 제한) |
| `_generate_response_streaming` | `(system_prompt, history) -> Generator[str]` | LLM 스트리밍 응답 생성 (delta.content yield) |
| `_generate_response_async` | `async (system_prompt, history) -> str` | LLM 비동기 응답 생성 (AsyncOpenAI) |

---

### 5.6. `cli.py` — 명령줄 인터페이스

> 개발/운영용 CLI. `python -m sc301.cli <command>` 또는 `python cli.py <command>` 형태로 실행.

#### 헬퍼 함수

| 함수 | 시그니처 | 설명 |
|------|----------|------|
| `get_core` | `(db_mode="aura") -> Core` | Core 인스턴스 팩토리 |
| `get_flow_engine` | `(core, fast_mode=False, model_override=None, consultation_scoring_mode="hybrid", intent_mode="hybrid") -> FlowEngine` | FlowEngine 인스턴스 팩토리. MODEL_PRESETS 기반 모델 선택 |
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
| `setup-schema` | `cmd_setup_schema(args)` | Neo4j constraints + vector index 생성 |
| `ingest <ttl_path>` | `cmd_ingest(args)` | TTL 파일 → Neo4j 적재 (`--no-embeddings` 옵션) |
| `turn <session_id> <user_text>` | `cmd_turn(args)` | 단일 턴 실행 (테스트용). QA 스토어 초기화 포함 |
| `repl [session_id]` | `cmd_repl(args)` | 대화형 REPL. QA 스토어 초기화 + 스트리밍/일반 모드 분기 |
| `repl-async [session_id]` | `cmd_repl_async(args)` → `_repl_async(args)` | 비동기 REPL (asyncio.run 래핑) |
| `health` | `cmd_health(args)` | OpenAI + Neo4j 연결 상태 확인 |
| `query <cypher>` | `cmd_query(args)` | Cypher 쿼리 직접 실행 (최대 20행 출력) |
| `sessions` | `cmd_list_sessions(args)` | 저장된 세션 목록 조회 (step, slots 수 표시) |

#### 공통 옵션

| 옵션 | 값 | 설명 |
|------|---|------|
| `--db` | `aura` \| `local` | Neo4j DB 모드 (기본: `aura`) |
| `--model` | `gpt-4o` \| `gpt-5` | LLM 모델 프리셋 |
| `--consultation-scoring` | `hybrid` \| `llm` \| `off` | 상담 Persona 스코어링 모드 (기본: `hybrid`) |
| `--intent-mode` | `rule` \| `llm` \| `hybrid` | Hybrid RAG 의도 분류 모드 (기본: `hybrid`) |

#### REPL 디버그 커맨드

| 커맨드 | 설명 |
|--------|------|
| `/state` | 현재 persona, scenario, step, slots, 상담 Persona 스코어 표시 |
| `/reset` | 세션 초기화 |
| `/cache` | 캐시 상태 표시 (embedding, step, persona) |
| `/clear-cache` | 전체 캐시 초기화 |

---

### 5.7. `jisikin/build_embeddings.py` — Q&A 임베딩 생성 스크립트

> `rag_docs.jsonl`의 각 문서에 대해 OpenAI 임베딩을 생성하고 `rag_docs.embeddings.npz`로 저장.

#### 상수

| 상수 | 값 | 설명 |
|------|---|------|
| `EMBED_MODEL` | `text-embedding-3-small` | 임베딩 모델 |
| `EMBED_DIM` | `1536` | 임베딩 차원 |
| `MAX_CHARS_PER_DOC` | `3000` | 문서당 최대 문자 수 |
| `DEFAULT_BATCH_SIZE` | `100` | API 배치 크기 |

#### 함수

| 함수 | 시그니처 | 설명 |
|------|----------|------|
| `load_jsonl` | `(jsonl_path) -> list[dict]` | JSONL 파일에서 문서 로드 |
| `build_embeddings` | `(client, docs, batch_size) -> np.ndarray` | 배치 임베딩 생성 + L2 정규화. `(N, 1536)` shape 반환 |
| `main` | `() -> None` | CLI 진입점. `--jsonl`, `--output`, `--batch-size` 옵션 |

#### 사용법

```bash
python jisikin/build_embeddings.py                    # 기본 실행
python jisikin/build_embeddings.py --batch-size 200   # 배치 크기 변경
python jisikin/build_embeddings.py --output custom.npz  # 출력 파일 변경
```

---

### 5.8. `patch_graph.py` — Neo4j 그래프 패치 스크립트

> 일회성 그래프 마이그레이션 스크립트. 기존 그래프의 구조적 문제를 수정.

#### 패치 목록

| 패치 상수 | Cypher 수 | 설명 |
|-----------|-----------|------|
| `PATCH_PERSONAL_INFO` | 10 | P1/P3/P4/P5 마무리 Step에 customerName, phoneNumber CheckItem 추가 |
| `PATCH_P5_SPLIT` | 8 | p5AskDetail 과밀 분리: 분기용 3개(breastCancerHistory, cancerSurgeryType, implantPresence)만 유지, 나머지 4개는 p5AskMedical로 이동. 흐름: p5AskDetail → p5AskMedical → p5InformSurgery 재연결 |
| `PATCH_CONSIDERS` | 4 | CONSIDERS 관계 누락 보완: ruleCancerConditional/NotAllowed에 Condition 추가, ruleImplantIntact/Damaged 노드 생성 + 연결 |

#### 함수

| 함수 | 시그니처 | 설명 |
|------|----------|------|
| `get_driver` | `(db_mode: str) -> Driver` | Neo4j 드라이버 생성 (환경변수 기반) |
| `run_patches` | `(driver, patches, label, dry_run=False) -> None` | 패치 쿼리 목록 순차 실행. 변경 통계 출력 (노드/관계 생성·삭제, 속성 설정) |
| `verify_patch` | `(driver) -> None` | 패치 결과 검증 (12개 검증 쿼리: 개인정보 존재, P1~P5 연결, 흐름 연결, CONSIDERS 확인) |
| `main` | `() -> None` | CLI 진입점. `--db` (local/aura), `--dry-run` (실행 없이 쿼리 출력) 옵션 |

---

### 5.9. `scripts/export_neo4j.py` — Neo4j 데이터 Cypher 내보내기

> 로컬 Neo4j 데이터를 Cypher 텍스트 파일로 내보내어 Community Edition에서 복원 가능하게 함.

#### 주요 특징

- embedding 프로퍼티 제외 (복원 후 `_create_embeddings()`로 새로 생성)
- 노드 고유 식별: `id` > `uri` > 첫 번째 속성 순으로 MATCH 패턴 생성
- 관계는 MATCH 기반 CREATE 문으로 생성 (변수 참조 불가한 cypher-shell 대응)

#### 함수

| 함수 | 시그니처 | 설명 |
|------|----------|------|
| `export_database` | `() -> None` | 전체 내보내기 실행. 4단계: Constraints → Indexes → 노드 → 관계. 결과를 `backups/neo4j_export.cypher`에 저장 |
| `serialize_props` | `(props: dict) -> str` | Python dict → Cypher 속성 리터럴 문자열 `{key: value, ...}` |
| `cypher_literal` | `(value) -> str` | Python 값 → Cypher 리터럴 (None→null, bool, int/float, str, list, dict 지원) |

---

### 5.10. `__init__.py` — 패키지 초기화

```python
__version__ = "0.1.0"
__all__ = ["ConversationState", "Core", "FlowEngine", "__version__"]
```

---

## 6. Neo4j Graph Structure

```
(Persona)--[:HAS_SCENARIO]-->(Scenario)--[:ASKS_FOR]-->(CheckItem)
                                |
                    +---(incoming TO 없는 Step = 시작)
                    |
                    v
                 (Step)--[:TO]-->(Step)--[:TO]-->...
                    |       |        |
            [:CHECKS]   [:GUIDED_BY]   [:REFERENCE]
                    |       |              |
                    v       v              v
              (CheckItem) (Guide)    (CheckItem)
                    |
              [:HAS_OPTION]-->(Option)

                 (Step)--[:RECOMMENDS]-->(Program)--[:HAS_SIDE_EFFECT]-->(SideEffect)

(Transition)--[:GUARDED_BY]-->(DecisionRule)--[:CONSIDERS]-->(Condition)
                                             +--[:WHEN]-->(ConditionGroup)--[:HAS_CONDITION]-->(Condition)

(Surgery)--[:causeSideEffect]-->(SideEffect)
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
| `CONSIDERS` | DecisionRule → Condition | 규칙의 조건 (권장, 1:N 정확한 매핑) |
| `WHEN` | DecisionRule → ConditionGroup | 규칙의 조건 그룹 (레거시) |
| `HAS_CONDITION` | ConditionGroup → Condition | 그룹의 조건 |

---

## 7. Personas

### 7.1. Flow Personas (시나리오 라우팅, 7개)

| ID | 이름 | 설명 | 주요 분기 |
|----|------|------|-----------|
| `slimBody` | 슬림바디 | 마른 체형, 지방이식 관심 | BMI 기반 STANDARD/LOW-FAT |
| `lipoCustomer` | 지방흡입고객 | 지방흡입+이식, 복합 시술 | upsellAccept → transferType |
| `skinTreatment` | 피부시술 | 피부 관리, 보톡스/필러, 레이저 | 분기 없음 (선형) |
| `longDistance` | 원거리고객 | 해외/지방 거주 | 거주지 → STANDARD/SEMI-REMOTE/FULL |
| `revisionFatigue` | 재수술피로 | 재수술, 보형물 제거/교체 | 유방암+보형물 → STANDARD/CONDITIONAL/NOT_ALLOWED |
| `P1_BreastConsult` | 가슴상담 | 레거시 (가슴 관련 범용) | — |
| `P2_FaceConsult` | 얼굴상담 | 레거시 (얼굴 관련 범용) | — |

### 7.2. Consultation Personas (톤/전략, 4차원)

| ID | 전략 | 유도 멘트 키워드 | 금기 |
|----|------|-----------------|------|
| `desire` | 공감 선행 후 안심 제공 | "고객님만을 위한 시간", "충분한 대화 시간 보장" | 수술결과만 강조, 비용 할인 압박 |
| `body` | 해부학적 전문성과 조화 강조 | "1:1 정밀 체형 분석", "균형잡힌 몸을 위한 통합 로드맵" | 트렌드 강요, 드라마틱한 변화 언급 |
| `social` | 고급스러움과 프라이버시 강조 | "프라이빗 예약", "티 나지 않는 디테일" | 흔한 사례 나열, 공개 장소 언급 |
| `service` | 수치와 팩트 위주 정보 전달 | "수술책임 보증제", "투명한 항목별 견적" | 추상적 수식어, 불투명한 추가 비용 |

---

## 8. Optimization Strategies

| 전략 | 위치 | 설명 |
|------|------|------|
| 1. 메모리 캐싱 | flow/engine.py | Step, Persona, Scenario, CheckItem, Condition 캐시 (TTL 5분) |
| 2. 임베딩 캐싱 | core.py | MD5 해시 기반 LRU 캐시 (최대 1000개) |
| 3. Q&A pickle 캐싱 | rag/store.py | 165K 문서+임베딩 pickle 캐시 (두 번째 로드부터 고속) |
| 4. 비동기 처리 | core.py, flow/turn.py | AsyncOpenAI, asyncio.to_thread, asyncio.gather |
| 5. Neo4j 연결 풀 | core.py | 최대 50개 연결, keep_alive, 타임아웃 설정 |
| 6. LLM 스트리밍 | flow/turn.py | SSE 스트리밍 응답 (REPL 실시간 출력) |
| 7. Vector Search 최적화 | core.py | min_score 필터링, Surgery+Step 합산 정렬, 중복 제거 |
| 8. 프롬프트 최적화 | flow/prompt.py | 히스토리 6턴 제한, 가이드 500자 제한 |
| 9. Hybrid RAG 의도 분류 | flow/rag_intent.py | rule 우선 + LLM fallback으로 불필요한 API 호출 최소화 |
| 10. FAISS 벡터 검색 | rag/store.py | FAISS IndexFlatIP로 165K 문서 대상 밀리초 단위 검색 |
| 11. LLM 호출 제거 | flow/persona.py | Persona 판별을 키워드+복합신호 기반으로 (LLM 미사용) |
| 12. 병렬 실행 | flow/turn.py | ThreadPoolExecutor로 slot 추출 + GraphRAG + QA 검색 3-way 동시 |
| 13. 자동 계산 | flow/slots.py | BMI, regionBucket 파생 슬롯 자동 산출 |

---

## 9. Environment Variables

```bash
# OpenAI
OPENAI_API_KEY=sk-...
OPENAI_EMBEDDING_MODEL=text-embedding-3-small    # 임베딩 모델
OPENAI_CHAT_MODEL=gpt-4o                         # 기본 채팅 모델
SLOT_EXTRACTION_MODEL=gpt-4o-mini                # 슬롯 추출 전용 (선택)
MAX_RESPONSE_TOKENS=500                           # LLM 최대 응답 토큰

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
```

---

## 10. Data Flow Summary

```
[사용자 발화]
     |
     v
+-- CLI (cli.py) -------------------------------------------+
|  cmd_repl() / cmd_turn()                                   |
|  -> FileStateStorage.load() -> state                       |
|  -> core.init_qa_store()  (data/ Q&A 벡터 스토어 로드)    |
|  -> FlowEngine.process_turn()                              |
|     |                                                      |
|     +-->  resolve_persona_scenario()                       |
|     |     +-->  Neo4j: QUERY_ALL_PERSONAS                  |
|     |     +-->  _score_personas() (로컬)                   |
|     |                                                      |
|     +-->  [병렬 3-way]                                     |
|     |     +-->  extract_slots()                            |
|     |     |     +-->  OpenAI: JSON mode                    |
|     |     |                                                |
|     |     +-->  _do_graph_rag_search()                     |
|     |     |     +-->  OpenAI: embed()                      |
|     |     |     +-->  Neo4j: Vector Index                  |
|     |     |                                                |
|     |     +-->  _do_qa_search()                            |
|     |           +-->  OpenAI: embed() (캐시)               |
|     |           +-->  rag/store: FAISS 벡터 검색            |
|     |                                                      |
|     +-->  auto_compute_slots() (로컬 계산)                 |
|     +-->  score_consultation_persona()                     |
|     |     +-->  OpenAI (hybrid/llm mode)                   |
|     |                                                      |
|     +-->  _classify_user_intent()                          |
|     |     +-->  rule/llm/hybrid 의도 분류                  |
|     +-->  _assemble_rag_context()                          |
|     |     +-->  의도 기반 GraphRAG + QA 컨텍스트 조합      |
|     |                                                      |
|     +-->  next_step()                                      |
|     |     +-->  Neo4j: QUERY_NEXT_STEPS_BY_TO              |
|     |     +-->  evaluate conditions (로컬+DB)              |
|     |                                                      |
|     +-->  build_step_prompt() (로컬)                       |
|     |                                                      |
|     +-->  _generate_response()                             |
|           +-->  OpenAI: ChatCompletion                     |
|                                                            |
|  -> FileStateStorage.save() -> state                       |
+------------------------------------------------------------+
     |
     v
[챗봇 응답]
```
