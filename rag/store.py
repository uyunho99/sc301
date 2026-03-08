"""
rag_store.py - Q&A 벡터 스토어 (Hybrid RAG)

jisikin/ 폴더 기반 일반 Q&A 검색 엔진.
GraphRAG 보충(시술 설명)과 오프스크립트 질문 대응에 사용.

데이터: jisikin/rag_docs.jsonl + rag_docs.embeddings.npz
저장: pickle 캐시 (rag_cache.pkl)
검색: FAISS IndexFlatIP (코사인 유사도)
"""

from __future__ import annotations
import os
import json
import pickle
import logging
from dataclasses import dataclass

import numpy as np
import faiss

logger = logging.getLogger(__name__)


@dataclass
class JisikinEntry:
    """지식인 Q&A 단일 항목"""
    id: str              # "K_0", "K_1", ...
    content: str         # "질문: ...\n답변: ..."
    question: str        # metadata.question
    answer: str          # metadata.answer


@dataclass
class QASearchResult:
    """Q&A 검색 결과"""
    entry: JisikinEntry
    score: float


class QAVectorStore:
    """
    jisikin/ JSONL+NPZ 기반 FAISS 벡터 스토어.

    초기화 흐름:
    1. load_from_cache() 시도 (pickle)
    2. 실패 시 load_from_jsonl() → save_cache()
    """

    def __init__(self):
        self.entries: list[JisikinEntry] = []
        self._index: faiss.Index | None = None
        self._is_ready: bool = False

    @property
    def is_ready(self) -> bool:
        return self._is_ready and self._index is not None

    # =========================================================================
    # 데이터 로드
    # =========================================================================

    def load_from_jsonl(
        self,
        jsonl_path: str,
        npz_path: str,
    ) -> int:
        """JSONL에서 문서 로드 + NPZ에서 사전 임베딩 로드.

        Args:
            jsonl_path: rag_docs.jsonl 경로
            npz_path: rag_docs.embeddings.npz 경로

        Returns:
            로드된 항목 수
        """
        # 1. JSONL 로드
        self.entries = []
        with open(jsonl_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                doc = json.loads(line)
                meta = doc.get("metadata", {}) or {}
                entry = JisikinEntry(
                    id=doc.get("id", ""),
                    content=doc.get("content", ""),
                    question=meta.get("question", ""),
                    answer=meta.get("answer", ""),
                )
                self.entries.append(entry)

        logger.info(f"JSONL 로드: {len(self.entries)}건 ({jsonl_path})")

        # 2. NPZ 임베딩 로드
        if not os.path.exists(npz_path):
            logger.warning(
                f"NPZ 파일 없음: {npz_path}\n"
                f"  → 'python jisikin/build_embeddings.py' 를 실행하여 임베딩을 생성하세요."
            )
            return len(self.entries)

        try:
            data = np.load(npz_path, allow_pickle=True)
            embeddings = data["embeddings"]  # (N, dim), 이미 L2 정규화됨
        except Exception as e:
            logger.error(
                f"NPZ 로드 실패: {e}\n"
                f"  → numpy 버전 호환 문제일 수 있습니다.\n"
                f"  → 'python jisikin/build_embeddings.py' 로 임베딩을 재생성하세요."
            )
            return len(self.entries)

        # ID 순서 검증
        try:
            if "ids" in data:
                npz_ids = data["ids"].tolist()
                entry_ids = [e.id for e in self.entries]
                if npz_ids != entry_ids:
                    logger.warning(
                        f"NPZ ids와 JSONL ids 불일치 "
                        f"(NPZ: {len(npz_ids)}건, JSONL: {len(entry_ids)}건). "
                        f"길이 기준으로 매칭합니다."
                    )
        except Exception:
            logger.warning("NPZ ids 검증 스킵 (로드 불가)")

        if len(embeddings) != len(self.entries):
            logger.warning(
                f"임베딩 수({len(embeddings)})와 문서 수({len(self.entries)}) 불일치. "
                f"최소값 기준으로 매칭합니다."
            )
            min_len = min(len(embeddings), len(self.entries))
            self.entries = self.entries[:min_len]
            embeddings = embeddings[:min_len]

        # FAISS 인덱스 구축 (L2 정규화된 벡터 → Inner Product = Cosine Similarity)
        embeddings = embeddings.astype(np.float32)
        dim = embeddings.shape[1]
        self._index = faiss.IndexFlatIP(dim)
        self._index.add(embeddings)
        self._is_ready = True

        logger.info(
            f"Q&A FAISS 인덱스 구축 완료: {len(self.entries)}건, "
            f"dim: {dim}, ntotal: {self._index.ntotal}"
        )
        return len(self.entries)

    def load_from_cache(self, cache_path: str) -> bool:
        """pickle 캐시에서 로드.

        Returns:
            성공 여부
        """
        if not os.path.exists(cache_path):
            return False

        try:
            with open(cache_path, "rb") as f:
                data = pickle.load(f)

            self.entries = data["entries"]

            # FAISS 인덱스 역직렬화
            index_bytes = data["faiss_index"]
            self._index = faiss.deserialize_index(
                np.frombuffer(index_bytes, dtype=np.uint8)
            )
            self._is_ready = True

            logger.info(f"Q&A FAISS 캐시 로드 완료: {len(self.entries)}건 ({cache_path})")
            return True
        except Exception as e:
            logger.warning(f"Q&A 캐시 로드 실패: {e}")
            return False

    def save_cache(self, cache_path: str) -> None:
        """현재 상태를 pickle 캐시로 저장."""
        if not self.entries or self._index is None:
            return

        # FAISS 인덱스 직렬화
        index_bytes = faiss.serialize_index(self._index).tobytes()

        data = {
            "entries": self.entries,
            "faiss_index": index_bytes,
        }
        with open(cache_path, "wb") as f:
            pickle.dump(data, f)

        logger.info(f"Q&A FAISS 캐시 저장 완료: {len(self.entries)}건 → {cache_path}")

    # =========================================================================
    # 검색
    # =========================================================================

    def search(
        self,
        query_embedding: list[float],
        k: int = 3,
        min_score: float = 0.45,
    ) -> list[QASearchResult]:
        """FAISS 기반 Q&A 검색.

        Args:
            query_embedding: 쿼리 임베딩 벡터 (L2 정규화 권장)
            k: 반환할 최대 결과 수
            min_score: 최소 유사도 점수

        Returns:
            QASearchResult 리스트 (점수 내림차순)
        """
        if not self.is_ready or self._index is None:
            return []

        query_vec = np.array([query_embedding], dtype=np.float32)
        # 쿼리 벡터 L2 정규화
        norm = np.linalg.norm(query_vec)
        if norm > 0:
            query_vec = query_vec / norm

        scores, indices = self._index.search(query_vec, k)

        results = []
        for score, idx in zip(scores[0], indices[0]):
            if idx < 0 or score < min_score:
                continue
            results.append(QASearchResult(
                entry=self.entries[idx],
                score=float(score),
            ))

        return results
