"""
core.py - 인프라 레이어

OpenAI LLM, Neo4j AuraDB, Embedding, Vector RAG를 통합 관리.
TTL 파싱 및 Neo4j ingestion 기능 포함.

최적화 내용:
- 전략 2: 임베딩 캐싱 (MD5 해시 기반)
- 전략 5: Neo4j 연결 풀링 최적화
- 전략 7: Vector Search 최적화 (min_score 필터링)
"""

from __future__ import annotations
import os
import logging
import hashlib
import time
import asyncio
from typing import Any
from dataclasses import dataclass
from collections import OrderedDict

from openai import OpenAI, AsyncOpenAI
from neo4j import GraphDatabase, Driver
from rdflib import Graph, Namespace, RDF, RDFS

try:
    from .schema import (
        SCHEMA_QUERIES,
        VECTOR_INDEX_QUERIES,
        TTL_NAMESPACES,
        QUERY_VECTOR_SEARCH_SURGERY,
        QUERY_VECTOR_SEARCH_STEP,
        QUERY_MERGE_PERSONA,
        QUERY_MERGE_SCENARIO,
        QUERY_MERGE_STEP,
        QUERY_MERGE_CHECKITEM,
        QUERY_MERGE_SURGERY,
        QUERY_MERGE_SIDEEFFECT,
        QUERY_MERGE_GUIDE,
        QUERY_MERGE_PROGRAM,
        QUERY_MERGE_OPTION,
        QUERY_CREATE_REL_HAS_SCENARIO,
        QUERY_CREATE_REL_STARTS_AT,
        QUERY_CREATE_REL_HAS_STEP,
        QUERY_CREATE_REL_STEP_TO,
        QUERY_CREATE_REL_LEADS_TO,
        QUERY_CREATE_REL_CHECKS,
        QUERY_CREATE_REL_ASKS_FOR,
        QUERY_CREATE_REL_GUIDED_BY,
        QUERY_CREATE_REL_RECOMMENDS,
        QUERY_CREATE_REL_REFERENCE,
        QUERY_CREATE_REL_HAS_OPTION,
        QUERY_CREATE_REL_HAS_SIDE_EFFECT,
        QUERY_CREATE_REL_CAUSE_SIDEEFFECT,
        QUERY_UPDATE_EMBEDDING,
        extract_local_id,
    )
except ImportError:
    from schema import (
        SCHEMA_QUERIES,
        VECTOR_INDEX_QUERIES,
        TTL_NAMESPACES,
        QUERY_VECTOR_SEARCH_SURGERY,
        QUERY_VECTOR_SEARCH_STEP,
        QUERY_MERGE_PERSONA,
        QUERY_MERGE_SCENARIO,
        QUERY_MERGE_STEP,
        QUERY_MERGE_CHECKITEM,
        QUERY_MERGE_SURGERY,
        QUERY_MERGE_SIDEEFFECT,
        QUERY_MERGE_GUIDE,
        QUERY_MERGE_PROGRAM,
        QUERY_MERGE_OPTION,
        QUERY_CREATE_REL_HAS_SCENARIO,
        QUERY_CREATE_REL_STARTS_AT,
        QUERY_CREATE_REL_HAS_STEP,
        QUERY_CREATE_REL_STEP_TO,
        QUERY_CREATE_REL_LEADS_TO,
        QUERY_CREATE_REL_CHECKS,
        QUERY_CREATE_REL_ASKS_FOR,
        QUERY_CREATE_REL_GUIDED_BY,
        QUERY_CREATE_REL_RECOMMENDS,
        QUERY_CREATE_REL_REFERENCE,
        QUERY_CREATE_REL_HAS_OPTION,
        QUERY_CREATE_REL_HAS_SIDE_EFFECT,
        QUERY_CREATE_REL_CAUSE_SIDEEFFECT,
        QUERY_UPDATE_EMBEDDING,
        extract_local_id,
    )

logger = logging.getLogger(__name__)


@dataclass
class CoreConfig:
    """Core 설정"""
    # OpenAI
    openai_api_key: str
    openai_embedding_model: str = "text-embedding-3-small"
    openai_chat_model: str = "gpt-4o"

    # Neo4j
    neo4j_uri: str = ""
    neo4j_user: str = "neo4j"
    neo4j_password: str = ""

    # Neo4j 연결 풀 설정 (전략 5)
    neo4j_max_connection_pool_size: int = 50
    neo4j_connection_acquisition_timeout: float = 60.0
    neo4j_max_connection_lifetime: int = 3600
    neo4j_connection_timeout: float = 30.0
    neo4j_keep_alive: bool = True

    @classmethod
    def from_env(cls, db_mode: str = "aura") -> "CoreConfig":
        """환경변수에서 설정 로드

        Args:
            db_mode: "aura" (Neo4j AuraDB) 또는 "local" (로컬 Neo4j)
        """
        # db_mode에 따라 Neo4j 환경변수 프리픽스 결정
        if db_mode == "local":
            prefix = "NEO4J_LOCAL"
        else:
            prefix = "NEO4J_AURA"

        return cls(
            openai_api_key=os.environ.get("OPENAI_API_KEY", ""),
            openai_embedding_model=os.environ.get("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small"),
            openai_chat_model=os.environ.get("OPENAI_CHAT_MODEL", "gpt-4o"),
            neo4j_uri=os.environ.get(f"{prefix}_URI", ""),
            neo4j_user=os.environ.get(f"{prefix}_USER", "neo4j"),
            neo4j_password=os.environ.get(f"{prefix}_PASSWORD", ""),
            neo4j_max_connection_pool_size=int(os.environ.get("NEO4J_MAX_POOL_SIZE", "50")),
            neo4j_connection_acquisition_timeout=float(os.environ.get("NEO4J_ACQUISITION_TIMEOUT", "60.0")),
            neo4j_max_connection_lifetime=int(os.environ.get("NEO4J_MAX_CONNECTION_LIFETIME", "3600")),
            neo4j_connection_timeout=float(os.environ.get("NEO4J_CONNECTION_TIMEOUT", "30.0")),
            neo4j_keep_alive=os.environ.get("NEO4J_KEEP_ALIVE", "true").lower() == "true",
        )


@dataclass
class Chunk:
    """검색 결과 청크"""
    id: str
    content: str
    metadata: dict[str, Any]
    score: float = 0.0


class Core:
    """인프라 통합 클래스"""

    def __init__(self, config: CoreConfig):
        self.config = config

        # OpenAI 클라이언트
        self.openai = OpenAI(api_key=config.openai_api_key)

        # 비동기 OpenAI 클라이언트 (전략 4)
        self.async_openai = AsyncOpenAI(api_key=config.openai_api_key)

        # Neo4j 드라이버 (전략 5: 연결 풀 최적화)
        self.driver: Driver | None = None
        if config.neo4j_uri:
            self.driver = GraphDatabase.driver(
                config.neo4j_uri,
                auth=(config.neo4j_user, config.neo4j_password),
                max_connection_pool_size=config.neo4j_max_connection_pool_size,
                connection_acquisition_timeout=config.neo4j_connection_acquisition_timeout,
                max_connection_lifetime=config.neo4j_max_connection_lifetime,
                connection_timeout=config.neo4j_connection_timeout,
                keep_alive=config.neo4j_keep_alive,
            )

        # 임베딩 캐시 (전략 2)
        self._embedding_cache: OrderedDict[str, list[float]] = OrderedDict()
        self._embedding_cache_max_size: int = 1000

    def close(self):
        """리소스 정리"""
        if self.driver:
            self.driver.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    # =========================================================================
    # 임베딩 캐시 유틸리티 (전략 2)
    # =========================================================================

    def _get_embedding_cache_key(self, text: str) -> str:
        """텍스트의 MD5 해시를 캐시 키로 생성"""
        normalized = text.strip().lower()
        return hashlib.md5(normalized.encode('utf-8')).hexdigest()

    def clear_embedding_cache(self) -> None:
        """임베딩 캐시 초기화"""
        self._embedding_cache.clear()

    # =========================================================================
    # Embedding (전략 2: 캐싱 적용)
    # =========================================================================

    def embed(self, text: str) -> list[float]:
        """텍스트를 벡터로 변환 (캐싱 적용)"""
        cache_key = self._get_embedding_cache_key(text)

        # 캐시 확인
        if cache_key in self._embedding_cache:
            # LRU: 최근 사용으로 이동
            self._embedding_cache.move_to_end(cache_key)
            return self._embedding_cache[cache_key]

        # API 호출
        response = self.openai.embeddings.create(
            model=self.config.openai_embedding_model,
            input=text
        )
        embedding = response.data[0].embedding

        # 캐시에 저장 (최대 크기 초과 시 가장 오래된 항목 제거)
        if len(self._embedding_cache) >= self._embedding_cache_max_size:
            self._embedding_cache.popitem(last=False)
        self._embedding_cache[cache_key] = embedding

        return embedding

    # =========================================================================
    # 비동기 Embedding (전략 4)
    # =========================================================================

    async def embed_async(self, text: str) -> list[float]:
        """비동기 임베딩 생성 (캐싱 적용)"""
        cache_key = self._get_embedding_cache_key(text)

        # 캐시 확인
        if cache_key in self._embedding_cache:
            self._embedding_cache.move_to_end(cache_key)
            return self._embedding_cache[cache_key]

        # 비동기 API 호출
        response = await self.async_openai.embeddings.create(
            model=self.config.openai_embedding_model,
            input=text
        )
        embedding = response.data[0].embedding

        # 캐시에 저장
        if len(self._embedding_cache) >= self._embedding_cache_max_size:
            self._embedding_cache.popitem(last=False)
        self._embedding_cache[cache_key] = embedding

        return embedding

    # =========================================================================
    # Vector Search (전략 7: min_score 필터링)
    # =========================================================================

    def vector_search(
        self,
        question: str,
        k: int = 5,
        search_type: str = "surgery",
        min_score: float = 0.5
    ) -> list[Chunk]:
        """Neo4j Vector Index에서 유사 청크 검색 (min_score 필터링)"""
        if not self.driver:
            raise RuntimeError("Neo4j 드라이버가 초기화되지 않음")

        embedding = self.embed(question)

        if search_type == "surgery":
            query = QUERY_VECTOR_SEARCH_SURGERY
        elif search_type == "step":
            query = QUERY_VECTOR_SEARCH_STEP
        else:
            raise ValueError(f"지원하지 않는 search_type: {search_type}")

        with self.driver.session() as session:
            result = session.run(query, embedding=embedding, k=k)
            chunks = []
            for record in result:
                score = record["score"]
                # min_score 미만 결과 제외 (전략 7)
                if score < min_score:
                    continue
                content = f"{record.get('name', '')}: {record.get('desc', '')}"
                chunks.append(Chunk(
                    id=record["id"],
                    content=content.strip(),
                    metadata={
                        "name": record.get("name"),
                        "category": record.get("category"),
                        "stepType": record.get("stepType"),
                    },
                    score=score
                ))
            return chunks

    def vector_search_combined(
        self,
        question: str,
        k: int = 2,
        min_score: float = 0.5
    ) -> list[Chunk]:
        """Surgery와 Step 모두에서 검색하여 합침 (전략 7: 최적화)"""
        surgery_chunks = self.vector_search(
            question, k=k, search_type="surgery", min_score=min_score
        )
        step_chunks = self.vector_search(
            question, k=k, search_type="step", min_score=min_score
        )

        # 점수 기준으로 합치고 정렬
        all_chunks = surgery_chunks + step_chunks
        all_chunks.sort(key=lambda x: x.score, reverse=True)

        # 중복 제거 후 상위 k*2개만 반환
        seen_ids = set()
        unique_chunks = []
        for chunk in all_chunks:
            if chunk.id not in seen_ids:
                seen_ids.add(chunk.id)
                unique_chunks.append(chunk)
                if len(unique_chunks) >= k * 2:
                    break

        return unique_chunks

    # =========================================================================
    # 비동기 Vector Search (전략 4)
    # =========================================================================

    async def vector_search_async(
        self,
        question: str,
        k: int = 5,
        search_type: str = "surgery",
        min_score: float = 0.5
    ) -> list[Chunk]:
        """비동기 벡터 검색"""
        if not self.driver:
            raise RuntimeError("Neo4j 드라이버가 초기화되지 않음")

        embedding = await self.embed_async(question)

        if search_type == "surgery":
            query = QUERY_VECTOR_SEARCH_SURGERY
        elif search_type == "step":
            query = QUERY_VECTOR_SEARCH_STEP
        else:
            raise ValueError(f"지원하지 않는 search_type: {search_type}")

        # Neo4j 쿼리를 비동기로 래핑
        def run_query():
            with self.driver.session() as session:
                result = session.run(query, embedding=embedding, k=k)
                chunks = []
                for record in result:
                    score = record["score"]
                    if score < min_score:
                        continue
                    content = f"{record.get('name', '')}: {record.get('desc', '')}"
                    chunks.append(Chunk(
                        id=record["id"],
                        content=content.strip(),
                        metadata={
                            "name": record.get("name"),
                            "category": record.get("category"),
                            "stepType": record.get("stepType"),
                        },
                        score=score
                    ))
                return chunks

        return await asyncio.to_thread(run_query)

    async def vector_search_combined_async(
        self,
        question: str,
        k: int = 2,
        min_score: float = 0.5
    ) -> list[Chunk]:
        """Surgery와 Step 동시 검색 (비동기 병렬 실행)"""
        surgery_task = self.vector_search_async(
            question, k=k, search_type="surgery", min_score=min_score
        )
        step_task = self.vector_search_async(
            question, k=k, search_type="step", min_score=min_score
        )

        surgery_chunks, step_chunks = await asyncio.gather(surgery_task, step_task)

        # 점수 기준으로 합치고 정렬
        all_chunks = surgery_chunks + step_chunks
        all_chunks.sort(key=lambda x: x.score, reverse=True)

        # 중복 제거 후 상위 k*2개만 반환
        seen_ids = set()
        unique_chunks = []
        for chunk in all_chunks:
            if chunk.id not in seen_ids:
                seen_ids.add(chunk.id)
                unique_chunks.append(chunk)
                if len(unique_chunks) >= k * 2:
                    break

        return unique_chunks

    # =========================================================================
    # Schema Management
    # =========================================================================

    def ensure_schema(self) -> None:
        """Neo4j에 constraints와 indexes 생성"""
        if not self.driver:
            raise RuntimeError("Neo4j 드라이버가 초기화되지 않음")

        with self.driver.session() as session:
            # Constraints 생성
            for query in SCHEMA_QUERIES:
                try:
                    session.run(query)
                    logger.info(f"Schema 실행 완료: {query[:50]}...")
                except Exception as e:
                    logger.warning(f"Schema 실행 실패 (무시 가능): {e}")

            # Vector Indexes 생성
            for query in VECTOR_INDEX_QUERIES:
                try:
                    session.run(query)
                    logger.info("Vector Index 생성 완료")
                except Exception as e:
                    logger.warning(f"Vector Index 생성 실패 (이미 존재할 수 있음): {e}")

        logger.info("Schema 설정 완료")

    # =========================================================================
    # TTL Ingestion
    # =========================================================================

    def ingest_documents(self, ttl_path: str, create_embeddings: bool = True) -> dict:
        """TTL 파일을 파싱하여 Neo4j에 적재"""
        if not self.driver:
            raise RuntimeError("Neo4j 드라이버가 초기화되지 않음")

        # TTL 파싱
        g = Graph()
        g.parse(ttl_path, format="turtle")

        # 네임스페이스 설정
        ONT = Namespace(TTL_NAMESPACES["ont"])

        stats = {
            "personas": 0,
            "scenarios": 0,
            "steps": 0,
            "checkitems": 0,
            "surgeries": 0,
            "sideeffects": 0,
            "guides": 0,
            "programs": 0,
            "options": 0,
            "relations": 0,
        }

        with self.driver.session() as session:
            # 1. 노드 생성
            stats.update(self._ingest_nodes(session, g, ONT))

            # 2. 관계 생성
            stats["relations"] = self._ingest_relations(session, g, ONT)

        # 3. Embeddings 생성 (선택적)
        if create_embeddings:
            self._create_embeddings()

        logger.info(f"Ingestion 완료: {stats}")
        return stats

    def _ingest_nodes(self, session, g: Graph, ONT: Namespace) -> dict:
        """노드 생성"""
        stats = {"personas": 0, "scenarios": 0, "steps": 0,
                 "checkitems": 0, "surgeries": 0, "sideeffects": 0,
                 "guides": 0, "programs": 0, "options": 0}

        # 타입별로 인스턴스 수집
        for s, p, o in g.triples((None, RDF.type, None)):
            type_local = extract_local_id(str(o))
            subj_id = extract_local_id(str(s))

            # 속성 수집
            props = self._collect_properties(g, s, ONT)

            if type_local == "Persona":
                session.run(QUERY_MERGE_PERSONA,
                           id=subj_id,
                           name=props.get("name", ""),
                           desc=props.get("desc", props.get("description", "")),
                           tags=props.get("tags", []))
                stats["personas"] += 1

            elif type_local == "Scenario":
                session.run(QUERY_MERGE_SCENARIO,
                           id=subj_id,
                           name=props.get("name", ""),
                           desc=props.get("desc", ""),
                           domain=props.get("domain", ""),
                           stageModel=props.get("stageModel", props.get("stage_model", "")))
                stats["scenarios"] += 1

            elif type_local == "Step":
                session.run(QUERY_MERGE_STEP,
                           id=subj_id,
                           desc=props.get("desc", ""),
                           stepType=props.get("stepType", props.get("type", "")))
                stats["steps"] += 1

            elif type_local == "CheckItem":
                session.run(QUERY_MERGE_CHECKITEM,
                           id=subj_id,
                           name=props.get("name", props.get("variableName", "")),
                           dataType=props.get("dataType", "string"))
                stats["checkitems"] += 1

            elif type_local == "Surgery":
                session.run(QUERY_MERGE_SURGERY,
                           id=subj_id,
                           name=props.get("name", ""),
                           desc=props.get("desc", ""),
                           category=props.get("category", ""))
                stats["surgeries"] += 1

            elif type_local == "SideEffect":
                session.run(QUERY_MERGE_SIDEEFFECT,
                           id=subj_id,
                           name=props.get("name", ""),
                           desc=props.get("desc", ""))
                stats["sideeffects"] += 1

            elif type_local == "Guide":
                session.run(QUERY_MERGE_GUIDE,
                           id=subj_id,
                           desc=props.get("desc", ""))
                stats["guides"] += 1

            elif type_local == "Program":
                session.run(QUERY_MERGE_PROGRAM,
                           id=subj_id,
                           name=props.get("name", ""),
                           desc=props.get("desc", props.get("description", "")),
                           category=props.get("category", ""))
                stats["programs"] += 1

            elif type_local == "Option":
                session.run(QUERY_MERGE_OPTION,
                           id=subj_id,
                           value=props.get("value", ""),
                           desc=props.get("desc", ""))
                stats["options"] += 1

        return stats

    def _collect_properties(self, g: Graph, subject, ONT: Namespace) -> dict:
        """주어진 subject의 모든 속성 수집"""
        props = {}

        # rdfs:label도 수집
        for o in g.objects(subject, RDFS.label):
            props["label"] = str(o)

        # ONT 네임스페이스의 데이터 속성들
        known_props = [
            "name", "desc", "description", "tags", "domain", "stageModel",
            "stage_model", "stepType", "type", "variableName", "category",
            "dataType", "value", "priority", "isDefault",
            "input", "op", "ref", "refType", "missingPolicy",
        ]
        for p, o in g.predicate_objects(subject):
            p_local = extract_local_id(str(p))
            if p_local in known_props:
                props[p_local] = str(o)

        return props

    def _ingest_relations(self, session, g: Graph, ONT: Namespace) -> int:
        """관계 생성"""
        count = 0

        relation_queries = {
            "hasScenario": QUERY_CREATE_REL_HAS_SCENARIO,
            "startsAt": QUERY_CREATE_REL_STARTS_AT,
            "hasStep": QUERY_CREATE_REL_HAS_STEP,
            "TO": QUERY_CREATE_REL_STEP_TO,
            "leadsTo": QUERY_CREATE_REL_LEADS_TO,
            "checks": QUERY_CREATE_REL_CHECKS,
            "CHECKS": QUERY_CREATE_REL_CHECKS,
            "asksFor": QUERY_CREATE_REL_ASKS_FOR,
            "ASKS_FOR": QUERY_CREATE_REL_ASKS_FOR,
            "guidedBy": QUERY_CREATE_REL_GUIDED_BY,
            "GUIDED_BY": QUERY_CREATE_REL_GUIDED_BY,
            "recommends": QUERY_CREATE_REL_RECOMMENDS,
            "RECOMMENDS": QUERY_CREATE_REL_RECOMMENDS,
            "REFERENCE": QUERY_CREATE_REL_REFERENCE,
            "hasOption": QUERY_CREATE_REL_HAS_OPTION,
            "HAS_OPTION": QUERY_CREATE_REL_HAS_OPTION,
            "hasSideEffect": QUERY_CREATE_REL_HAS_SIDE_EFFECT,
            "HAS_SIDE_EFFECT": QUERY_CREATE_REL_HAS_SIDE_EFFECT,
            "causeSideEffect": QUERY_CREATE_REL_CAUSE_SIDEEFFECT,
        }

        for s, p, o in g.triples((None, None, None)):
            p_local = extract_local_id(str(p))

            if p_local in relation_queries:
                from_id = extract_local_id(str(s))
                to_id = extract_local_id(str(o))

                params = self._get_relation_params(p_local, from_id, to_id)

                try:
                    session.run(relation_queries[p_local], **params)
                    count += 1
                except Exception as e:
                    logger.warning(f"관계 생성 실패 [{p_local}]: {e}")

        return count

    def _get_relation_params(self, rel_type: str, from_id: str, to_id: str) -> dict:
        """관계 타입에 따른 쿼리 파라미터 반환"""
        param_mapping = {
            "hasScenario": {"personaId": from_id, "scenarioId": to_id},
            "startsAt": {"scenarioId": from_id, "stepId": to_id},
            "hasStep": {"scenarioId": from_id, "stepId": to_id},
            "TO": {"fromStepId": from_id, "toStepId": to_id},
            "leadsTo": {"fromStepId": from_id, "toStepId": to_id},
            "checks": {"stepId": from_id, "checkItemId": to_id},
            "CHECKS": {"stepId": from_id, "checkItemId": to_id},
            "asksFor": {"scenarioId": from_id, "checkItemId": to_id},
            "ASKS_FOR": {"scenarioId": from_id, "checkItemId": to_id},
            "guidedBy": {"stepId": from_id, "guideId": to_id},
            "GUIDED_BY": {"stepId": from_id, "guideId": to_id},
            "recommends": {"stepId": from_id, "programId": to_id},
            "RECOMMENDS": {"stepId": from_id, "programId": to_id},
            "REFERENCE": {"stepId": from_id, "checkItemId": to_id},
            "hasOption": {"checkItemId": from_id, "optionId": to_id},
            "HAS_OPTION": {"checkItemId": from_id, "optionId": to_id},
            "hasSideEffect": {"programId": from_id, "sideEffectId": to_id},
            "HAS_SIDE_EFFECT": {"programId": from_id, "sideEffectId": to_id},
            "causeSideEffect": {"surgeryId": from_id, "sideEffectId": to_id},
        }
        return param_mapping.get(rel_type, {"fromId": from_id, "toId": to_id})

    def _create_embeddings(self) -> None:
        """노드들에 대한 임베딩 생성"""
        if not self.driver:
            return

        with self.driver.session() as session:
            # Surgery 임베딩
            result = session.run("MATCH (s:Surgery) RETURN s.id AS id, s.name AS name, s.desc AS desc")
            for record in result:
                text = f"{record['name']}: {record['desc'] or ''}"
                if text.strip():
                    embedding = self.embed(text)
                    session.run(QUERY_UPDATE_EMBEDDING, id=record["id"], embedding=embedding)

            # Step 임베딩
            result = session.run("MATCH (s:Step) RETURN s.id AS id, s.desc AS desc, s.type AS stepType")
            for record in result:
                text = f"[{record['stepType'] or ''}] {record['desc'] or ''}"
                if text.strip():
                    embedding = self.embed(text)
                    session.run(QUERY_UPDATE_EMBEDDING, id=record["id"], embedding=embedding)

        logger.info("Embeddings 생성 완료")

    # =========================================================================
    # Utility Methods
    # =========================================================================

    def run_query(self, query: str, **params) -> list[dict]:
        """임의의 Cypher 쿼리 실행"""
        if not self.driver:
            raise RuntimeError("Neo4j 드라이버가 초기화되지 않음")

        with self.driver.session() as session:
            result = session.run(query, **params)
            return [dict(record) for record in result]

    def health_check(self) -> dict:
        """연결 상태 확인"""
        status = {
            "openai": False,
            "neo4j": False,
            "embedding_cache_size": len(self._embedding_cache),
        }

        # OpenAI 체크
        try:
            self.openai.models.list()
            status["openai"] = True
        except Exception as e:
            logger.error(f"OpenAI 연결 실패: {e}")

        # Neo4j 체크
        if self.driver:
            try:
                with self.driver.session() as session:
                    session.run("RETURN 1")
                status["neo4j"] = True
            except Exception as e:
                logger.error(f"Neo4j 연결 실패: {e}")

        return status
