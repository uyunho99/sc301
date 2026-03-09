"""
flow/rag_postprocess.py - RAG 인용/후처리 유틸리티

ipynb(지식인 챗봇 코드2)에서 검증된 인용 시스템 + 후처리 파이프라인 포팅.
Case 2(페르소나 미매칭)와 Case 3(오프스크립트)에서 사용.
"""
from __future__ import annotations
import re

# =========================================================================
# 상수
# =========================================================================

MIN_SIM_RAG = 0.50          # 이 이상이면 RAG 컨텍스트 주입 + 인용
MIN_SIM_FALLBACK = 0.35     # 이 미만이면 답변 자체를 거부 (폴백)
MAX_CHARS_PER_DOC = 700     # LLM 컨텍스트에 주입 시 문서당 최대 글자수
TOP_K = 5                   # 최대 검색 문서 수

NO_REFERENCE_FALLBACK = (
    "죄송합니다. 현재 내부 지식베이스에서 해당 질문과 충분히 관련된 근거를 찾지 못해 "
    "정확한 답변을 드리기 어렵습니다.\n"
    "가능하시면 상담 내용을 조금 더 구체적으로 알려주시거나, "
    "내원/의료진 상담을 권유드립니다."
)

OFFSCRIPT_FALLBACK = (
    "[고객 질문 응대]\n"
    "고객이 현재 단계와 무관한 질문을 했습니다.\n"
    "해당 질문에 대한 충분한 참고 정보를 찾지 못해 정확히 안내드리기 어렵습니다. "
    "전문의 상담을 권장드립니다.\n"
    "간결하게 이 점을 안내한 뒤, 현재 단계의 질문으로 자연스럽게 돌아가세요."
)


# =========================================================================
# 컨텍스트 포맷팅
# =========================================================================

def format_rich_context(
    results: list,
    max_chars: int = MAX_CHARS_PER_DOC,
) -> str:
    """QASearchResult 리스트를 ipynb 스타일의 메타데이터 포함 컨텍스트로 포맷팅.

    출력 예:
        [참고 1] score=0.760, id=K_1234, date=2023-04-14, category=성형외과
        질문: ...
        답변: ... (max_chars로 절단)
    """
    blocks: list[str] = []
    for rank, r in enumerate(results, start=1):
        e = r.entry
        header = (
            f"[참고 {rank}] "
            f"score={r.score:.3f}, "
            f"id={e.id}, "
            f"date={e.date}, "
            f"category={e.category}, "
            f"a_tags={e.a_tags}"
        )
        content = (e.content or "")[:max_chars]
        blocks.append(header + "\n" + content)
    return "\n\n".join(blocks)


# =========================================================================
# 출처 맵 & 인용 규칙
# =========================================================================

def build_source_map(results: list) -> dict[int, str]:
    """rank → link 매핑 (link가 있는 문서만 포함)."""
    source_map: dict[int, str] = {}
    for rank, r in enumerate(results, start=1):
        link = (r.entry.link or "").strip()
        if link:
            source_map[rank] = link
    return source_map


def make_citation_instruction(source_map: dict[int, str]) -> str:
    """허용된 출처 번호만 사용하도록 LLM에 지시하는 텍스트."""
    allowed = ", ".join(f"[{k}]" for k in sorted(source_map.keys())) if source_map else ""
    return (
        "답변 작성 규칙:\n"
        "- 의학적 사실/권고/부작용/위험도/근거가 필요한 문장 끝에만 "
        "숫자 출처 표기([1] 형태)를 붙이세요.\n"
        "- 출처 표기는 반드시 문장 끝(가능하면 마침표 뒤)에 붙이세요. "
        "예: ...입니다.[1]\n"
        "- URL을 본문에 쓰거나, '(출처: ...)' 같은 텍스트를 절대 쓰지 마세요.\n"
        "- 아래 허용된 출처 번호만 사용하세요.\n"
        f"- 허용 출처 번호: {allowed}\n"
    )


# =========================================================================
# 후처리 파이프라인
# =========================================================================

def strip_model_written_sources(text: str) -> str:
    """모델이 자체적으로 작성한 '출처:' 섹션을 제거."""
    out = re.split(r'\n\s*(출처\s*:|\(출처\s*:)', text, maxsplit=1)[0].rstrip()
    return out


def normalize_citation_blocks(text: str) -> str:
    """인접 인용 표기 정규화: [1] [2] → [1][2], [1,2] → [1][2]."""
    out = re.sub(r'\[(\d+)\]\s+\[(\d+)\]', r'[\1][\2]', text)
    out = re.sub(r'\[(\d+)\s*,\s*(\d+)\]', r'[\1][\2]', out)
    return out


def extract_citation_numbers(text: str) -> list[int]:
    """답변 텍스트에서 사용된 인용 번호를 순서대로 추출 (중복 제거)."""
    nums = [int(x) for x in re.findall(r'\[(\d+)\]', text)]
    seen: set[int] = set()
    ordered: list[int] = []
    for n in nums:
        if n not in seen:
            ordered.append(n)
            seen.add(n)
    return ordered


def build_sources_section(
    cited_nums: list[int],
    source_map: dict[int, str],
) -> str:
    """인용된 번호에 대응하는 링크로 출처 섹션 생성."""
    lines: list[str] = []
    for n in cited_nums:
        link = source_map.get(n)
        if link:
            lines.append(f"- [{n}] {link}")
    if not lines:
        return ""
    return "출처:\n" + "\n".join(lines)


def postprocess_response(
    response: str,
    source_map: dict[int, str],
) -> str:
    """전체 후처리 파이프라인.

    1. 모델이 쓴 출처 섹션 제거
    2. 인용 표기 정규화
    3. 사용된 인용 번호 추출
    4. 시스템 생성 출처 섹션 추가
    """
    if not source_map:
        return response

    body = strip_model_written_sources(response)
    body = normalize_citation_blocks(body)
    cited = extract_citation_numbers(body)
    sources_section = build_sources_section(cited, source_map)
    if sources_section:
        return body + "\n\n" + sources_section
    return body
