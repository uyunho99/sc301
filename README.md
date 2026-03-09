# SC301 - Graph RAG 성형외과 상담 챗봇

Neo4j 그래프 온톨로지 기반 성형외과 상담 챗봇. Hybrid RAG(GraphRAG + 165K QA 벡터 스토어)로 구조화된 상담 흐름과 일반 질문 대응을 결합한다.

## 핵심 설계

- **Graph-Driven Flow**: 대화 흐름이 Neo4j 그래프의 `Persona → Scenario → Step` 관계로 정의
- **Hybrid RAG**: GraphRAG(Neo4j 벡터 검색) + QA 벡터 스토어(FAISS, 165K 문서)를 의도 분류 기반으로 결합
- **Slot-Based State**: 각 Step에서 수집해야 할 정보(CheckItem)를 slot으로 관리
- **Static Routing Table**: 분기 로직은 Python dict(`BRANCHING_RULES`)로 관리
- **Dual Persona Layer**: Flow 페르소나(시나리오 라우팅)와 상담 페르소나(톤/전략) 이원 구조

## 아키텍처

```
+-----------------------------------------------------------+
|  CLI Layer (cli.py, factories.py)                          |
|  - argparse 기반 진입점, REPL/단일턴/디버그                |
+-----------------------------------------------------------+
|  Business Logic Layer (flow/ 패키지)                       |
|  - FlowEngine: 7개 Mixin 기반 턴 처리 파이프라인           |
|  - persona, navigation, slots, consultation,               |
|    rag_intent, rag_postprocess, prompt, turn                |
+-----------------------------------------------------------+
|  RAG Layer (rag/store.py)                                  |
|  - QAVectorStore: FAISS IndexFlatIP 벡터 스토어            |
|  - pickle 캐시 (data/rag_cache.pkl)                        |
+-----------------------------------------------------------+
|  State Layer (state.py)                                    |
|  - ConversationState + File/Redis Storage                  |
+-----------------------------------------------------------+
|  Infrastructure Layer (core.py)                            |
|  - OpenAI 클라이언트, Neo4j 드라이버, 임베딩 캐시          |
|  - GraphRAG 벡터 검색, QA 스토어 초기화                    |
+-----------------------------------------------------------+
|  Config (config/) + Schema (schema/)                       |
|  - config/: 비즈니스 규칙 (분기, 슬롯, 상담 전략)          |
|  - schema/: Cypher 쿼리 상수, TTL Ingestion                |
+-----------------------------------------------------------+
     |                    |                    |
  Neo4j DB           OpenAI API          data/ (JSONL+NPZ)
```

## 프로젝트 구조

```
sc301/
├── cli.py                     # CLI 진입점
├── core.py                    # OpenAI + Neo4j + QA 스토어 통합
├── factories.py               # Core/FlowEngine/StateStorage 팩토리
├── state.py                   # 세션 상태 관리
├── config/                    # 비즈니스 규칙
│   ├── branching.py           #   정적 라우팅 테이블
│   ├── conditions.py          #   분기 조건 매핑
│   ├── consultation.py        #   상담 키워드/톤/전략
│   ├── guides.py              #   Guide 선택 규칙
│   └── slots.py               #   슬롯 자동계산/스킵/힌트
├── schema/                    # Neo4j 스키마
│   ├── queries.py             #   Cypher 쿼리 상수
│   ├── ingestion.py           #   TTL Ingestion Cypher
│   └── neo4j-aligned-schema.cypher
├── flow/                      # FlowEngine Mixin 패키지
│   ├── engine.py              #   Mixin 조합 + 캐시 관리
│   ├── persona.py             #   Persona 판별
│   ├── navigation.py          #   Step 전이 + 분기 평가
│   ├── slots.py               #   Slot 추출 + 자동 계산
│   ├── consultation.py        #   상담 Persona 스코어링
│   ├── rag_intent.py          #   Hybrid RAG 의도 분류
│   ├── rag_postprocess.py     #   RAG 후처리
│   ├── prompt.py              #   프롬프트 빌더
│   └── turn.py                #   process_turn 오케스트레이션
├── rag/                       # RAG 레이어
│   └── store.py               #   QAVectorStore (FAISS)
├── data/                      # RAG 데이터 (gitignore, 대용량)
│   ├── rag_docs.jsonl         #   165K Q&A 문서
│   ├── rag_docs.embeddings.npz#   사전 계산 임베딩
│   ├── rag_cache.pkl          #   pickle 캐시
│   └── sc301_system_prompt3.txt#  시스템 프롬프트
├── scripts/                   # 유틸리티 스크립트
├── test_scenarios.py          # 단위/통합 테스트 (23개)
├── test_repl.py               # REPL 시뮬레이션 (17개)
└── benchmark_scenarios.py     # 성능 벤치마크
```

## Quick Start

```bash
# 1. 의존성 설치
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 2. 환경 변수 설정
cp .env.enc .env  # 복호화 후 API 키/DB 접속정보 입력

# 3. Neo4j 스키마 설정
python cli.py setup-schema --db local

# 4. 연결 확인
python cli.py health --db local

# 5. 대화 시작
python cli.py repl --db local
```

## 주요 CLI 커맨드

| 커맨드 | 용도 |
|--------|------|
| `python cli.py repl --db local` | 대화형 REPL (스트리밍) |
| `python cli.py repl --db local --model gpt-5` | GPT-5 모델 사용 |
| `python cli.py repl --db local --fast` | Fast 모드 (gpt-4o-mini) |
| `python cli.py turn <session> "<text>" --db local` | 단일 턴 실행 |
| `python cli.py health --db local` | 연결 상태 확인 |
| `python cli.py setup-schema --db local` | Neo4j 스키마 설정 |

> `--db`: `aura` (AuraDB, 기본) / `local` (로컬 Neo4j)
> `--model`: `gpt-4o` (기본) / `gpt-5`

## 테스트

```bash
python test_scenarios.py                          # 단위/통합 23개 (LLM 불필요)
python test_repl.py --db local -s all             # REPL 시뮬레이션 17개
python test_repl.py --db local -s p1std --with-llm  # 실제 LLM으로 테스트
python benchmark_scenarios.py --db local          # 성능 벤치마크
```

> 상세 시나리오: [docs/TESTING.md](docs/TESTING.md)

## 문서

| 문서 | 내용 |
|------|------|
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | 코드 아키텍처, 모듈별 메서드 명세 |
| [docs/SETUP.md](docs/SETUP.md) | 환경 설정, CLI 레퍼런스, 트러블슈팅 |
| [docs/TESTING.md](docs/TESTING.md) | 테스트 시나리오 가이드 (17개 REPL + 23개 단위) |
| [GRAPH_RAG_SPEC.md](GRAPH_RAG_SPEC.md) | Graph RAG 온톨로지 설계 명세 |

## Tech Stack

Python 3.11+ / Neo4j (AuraDB / Local) / OpenAI (gpt-4o, gpt-5) / FAISS / numpy
