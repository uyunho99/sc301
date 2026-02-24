"""
benchmark_scenarios.py - 테스트 시나리오 기반 턴별 성능 측정

test_repl.py의 시나리오를 --with-llm 모드로 실행하면서
benchmark.py의 계측 래퍼로 턴별 세부 시간을 측정합니다.

사용법:
  python benchmark_scenarios.py --db local                    # 전체 시나리오 벤치마크
  python benchmark_scenarios.py --db local -s p1std           # 특정 시나리오만
  python benchmark_scenarios.py --db local --no-cache         # 캐시 비활성화 (순수 성능)
  python benchmark_scenarios.py --db local --csv result.csv   # CSV 내보내기
"""

from __future__ import annotations

import argparse
import csv
import io
import os
import sys
import time
import uuid
import logging
from dataclasses import dataclass, field
from typing import Any

from dotenv import load_dotenv
load_dotenv()

from core import Core, CoreConfig
from flow import FlowEngine
from state import ConversationState
from test_repl import TEST_SCENARIOS

# 로깅 최소화
logging.basicConfig(level=logging.WARNING)
logging.getLogger("neo4j").setLevel(logging.ERROR)
logging.getLogger("httpx").setLevel(logging.ERROR)


# =============================================================================
# 타이밍 기록
# =============================================================================

@dataclass
class TimingRecord:
    category: str       # "neo4j", "embedding", "llm", "neo4j+embed"
    operation: str
    duration_ms: float

@dataclass
class TurnTimings:
    turn_num: int
    step_id: str
    utterance: str
    total_ms: float = 0.0
    records: list[TimingRecord] = field(default_factory=list)

    def add(self, category: str, operation: str, duration_ms: float):
        self.records.append(TimingRecord(category, operation, duration_ms))

    def by_category(self) -> dict[str, float]:
        cats: dict[str, float] = {}
        for r in self.records:
            cats[r.category] = cats.get(r.category, 0.0) + r.duration_ms
        return cats

@dataclass
class ScenarioResult:
    key: str
    name: str
    turns: list[TurnTimings] = field(default_factory=list)

    @property
    def total_ms(self) -> float:
        return sum(t.total_ms for t in self.turns)

    def category_totals(self) -> dict[str, float]:
        cats: dict[str, float] = {}
        for t in self.turns:
            for r in t.records:
                cats[r.category] = cats.get(r.category, 0.0) + r.duration_ms
        return cats


# =============================================================================
# 계측 래퍼 (benchmark.py 기반)
# =============================================================================

class InstrumentedCore(Core):
    def __init__(self, config):
        super().__init__(config)
        self._current_turn: TurnTimings | None = None

    def set_current_turn(self, turn: TurnTimings):
        self._current_turn = turn

    def run_query(self, query: str, **params) -> list[dict]:
        t0 = time.perf_counter()
        result = super().run_query(query, **params)
        elapsed = (time.perf_counter() - t0) * 1000
        if self._current_turn:
            label = query.strip()[:60].replace('\n', ' ')
            self._current_turn.add("neo4j", label, elapsed)
        return result

    def embed(self, text: str) -> list[float]:
        t0 = time.perf_counter()
        result = super().embed(text)
        elapsed = (time.perf_counter() - t0) * 1000
        if self._current_turn:
            self._current_turn.add("embedding", f"embed({text[:30]}...)", elapsed)
        return result

    def vector_search_combined(self, question, k=2, min_score=0.5):
        t0 = time.perf_counter()
        result = super().vector_search_combined(question, k, min_score)
        elapsed = (time.perf_counter() - t0) * 1000
        if self._current_turn:
            self._current_turn.add("neo4j+embed", "vector_search_combined", elapsed)
        return result


class InstrumentedFlowEngine(FlowEngine):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._current_turn: TurnTimings | None = None

    def set_current_turn(self, turn: TurnTimings):
        self._current_turn = turn

    def get_all_personas(self):
        t0 = time.perf_counter()
        result = super().get_all_personas()
        elapsed = (time.perf_counter() - t0) * 1000
        if self._current_turn:
            self._current_turn.add("neo4j", "get_all_personas", elapsed)
        return result

    def get_persona(self, persona_id):
        t0 = time.perf_counter()
        result = super().get_persona(persona_id)
        elapsed = (time.perf_counter() - t0) * 1000
        if self._current_turn:
            self._current_turn.add("neo4j", f"get_persona({persona_id})", elapsed)
        return result

    def get_scenario(self, scenario_id):
        t0 = time.perf_counter()
        result = super().get_scenario(scenario_id)
        elapsed = (time.perf_counter() - t0) * 1000
        if self._current_turn:
            self._current_turn.add("neo4j", f"get_scenario({scenario_id})", elapsed)
        return result

    def get_step(self, step_id):
        t0 = time.perf_counter()
        result = super().get_step(step_id)
        elapsed = (time.perf_counter() - t0) * 1000
        if self._current_turn:
            self._current_turn.add("neo4j", f"get_step({step_id})", elapsed)
        return result

    def get_step_checks(self, step_id):
        t0 = time.perf_counter()
        result = super().get_step_checks(step_id)
        elapsed = (time.perf_counter() - t0) * 1000
        if self._current_turn:
            self._current_turn.add("neo4j", f"get_step_checks({step_id})", elapsed)
        return result

    def next_step(self, state):
        t0 = time.perf_counter()
        result = super().next_step(state)
        elapsed = (time.perf_counter() - t0) * 1000
        if self._current_turn:
            self._current_turn.add("neo4j", "next_step(transition)", elapsed)
        return result

    def extract_slots(self, state, user_text, step_id=None):
        t0 = time.perf_counter()
        result = super().extract_slots(state, user_text, step_id)
        elapsed = (time.perf_counter() - t0) * 1000
        if self._current_turn:
            self._current_turn.add("llm", "extract_slots", elapsed)
        return result

    def _generate_response(self, system_prompt, history):
        t0 = time.perf_counter()
        result = super()._generate_response(system_prompt, history)
        elapsed = (time.perf_counter() - t0) * 1000
        if self._current_turn:
            self._current_turn.add("llm", "generate_response", elapsed)
        return result

    def build_step_prompt(self, step_id, state, rag_context=""):
        t0 = time.perf_counter()
        result = super().build_step_prompt(step_id, state, rag_context)
        elapsed = (time.perf_counter() - t0) * 1000
        if self._current_turn:
            self._current_turn.add("logic", "build_step_prompt", elapsed)
        return result


# =============================================================================
# 색상 유틸리티
# =============================================================================

class C:
    RESET  = "\033[0m"
    BOLD   = "\033[1m"
    DIM    = "\033[2m"
    RED    = "\033[91m"
    GREEN  = "\033[92m"
    YELLOW = "\033[93m"
    BLUE   = "\033[94m"
    MAGENTA = "\033[95m"
    CYAN   = "\033[96m"
    GRAY   = "\033[90m"


def bar(value: float, max_value: float, width: int = 30) -> str:
    """수평 막대 그래프"""
    if max_value <= 0:
        return ""
    filled = int(value / max_value * width)
    filled = min(filled, width)
    return f"{'█' * filled}{'░' * (width - filled)}"


# =============================================================================
# 시나리오 벤치마크 실행
# =============================================================================

def run_scenario_benchmark(
    engine: InstrumentedFlowEngine,
    core: InstrumentedCore,
    scenario_key: str,
    disable_cache: bool = False,
) -> ScenarioResult:
    """단일 시나리오를 process_turn()으로 실행하면서 타이밍 측정"""

    sc = TEST_SCENARIOS[scenario_key]
    result = ScenarioResult(key=scenario_key, name=sc["name"])

    state = ConversationState(session_id=f"bench_{scenario_key}_{uuid.uuid4().hex[:6]}")
    state.persona_id = sc["persona"]
    state.scenario_id = sc["scenario"]

    # 시작 Step 설정
    scenario_data = engine.get_scenario(sc["scenario"])
    start_step = scenario_data.get("startStepId") if scenario_data else None
    if not start_step:
        print(f"  {C.RED}시작 Step을 찾을 수 없음: {sc['scenario']}{C.RESET}")
        return result
    state.current_step_id = start_step

    print(f"\n  {C.BOLD}{C.CYAN}{'=' * 68}{C.RESET}")
    print(f"  {C.BOLD}{C.CYAN}  {sc['name']}{C.RESET}")
    print(f"  {C.BOLD}{C.CYAN}{'=' * 68}{C.RESET}")

    for i, turn_data in enumerate(sc["turns"]):
        if disable_cache:
            engine.clear_cache()

        utterance = turn_data["utterance"]
        step_id = state.current_step_id or "?"

        turn = TurnTimings(turn_num=i + 1, step_id=step_id, utterance=utterance)
        core.set_current_turn(turn)
        engine.set_current_turn(turn)

        t0 = time.perf_counter()

        try:
            response, state = engine.process_turn(state, utterance, core=core)
        except Exception as e:
            response = f"[오류: {e}]"

        turn.total_ms = (time.perf_counter() - t0) * 1000
        result.turns.append(turn)

        # 턴 결과 출력
        cats = turn.by_category()
        max_cat_ms = max(cats.values()) if cats else 1

        print(f"\n  {C.MAGENTA}Turn {i+1}{C.RESET} [{C.DIM}{step_id}{C.RESET}] {C.BOLD}{turn.total_ms:,.0f}ms{C.RESET}")
        print(f"  {C.DIM}입력: {utterance[:70]}{'...' if len(utterance) > 70 else ''}{C.RESET}")
        print(f"  {C.DIM}응답: {str(response)[:70]}{'...' if len(str(response)) > 70 else ''}{C.RESET}")

        # 카테고리별 시간 막대
        for cat, ms in sorted(cats.items(), key=lambda x: -x[1]):
            pct = ms / turn.total_ms * 100 if turn.total_ms > 0 else 0
            color = C.RED if pct > 50 else C.YELLOW if pct > 20 else C.GREEN
            print(f"    {color}{cat:15s}{C.RESET} {ms:>7,.0f}ms ({pct:4.1f}%) {bar(ms, turn.total_ms, 25)}")

        # 세부 기록 (가장 느린 3개)
        slow = sorted(turn.records, key=lambda r: -r.duration_ms)[:3]
        for r in slow:
            print(f"      {C.DIM}└─ {r.category}: {r.operation} = {r.duration_ms:,.0f}ms{C.RESET}")

    return result


# =============================================================================
# 결과 요약
# =============================================================================

def print_summary(results: list[ScenarioResult]):
    """전체 결과 요약"""
    print(f"\n{'='*72}")
    print(f"  {C.BOLD}{C.CYAN}전체 벤치마크 결과 요약{C.RESET}")
    print(f"{'='*72}")

    # 시나리오별 요약 테이블
    print(f"\n  {C.BOLD}시나리오별 총 소요 시간{C.RESET}")
    print(f"  {'시나리오':<35s} {'턴수':>4s} {'총시간':>10s} {'턴평균':>10s}")
    print(f"  {'-'*35} {'-'*4} {'-'*10} {'-'*10}")

    grand_total_ms = 0
    grand_total_turns = 0

    for r in results:
        n = len(r.turns)
        avg = r.total_ms / n if n > 0 else 0
        grand_total_ms += r.total_ms
        grand_total_turns += n
        print(f"  {r.name:<35s} {n:>4d} {r.total_ms:>9,.0f}ms {avg:>9,.0f}ms")

    grand_avg = grand_total_ms / grand_total_turns if grand_total_turns > 0 else 0
    print(f"  {'-'*35} {'-'*4} {'-'*10} {'-'*10}")
    print(f"  {'합계':<35s} {grand_total_turns:>4d} {grand_total_ms:>9,.0f}ms {grand_avg:>9,.0f}ms")

    # 카테고리별 누적 시간
    print(f"\n  {C.BOLD}카테고리별 누적 시간{C.RESET}")
    all_cats: dict[str, float] = {}
    for r in results:
        for cat, ms in r.category_totals().items():
            all_cats[cat] = all_cats.get(cat, 0.0) + ms

    print(f"  {'카테고리':<20s} {'누적시간':>10s} {'비율':>8s}  그래프")
    print(f"  {'-'*20} {'-'*10} {'-'*8}  {'-'*30}")

    max_cat = max(all_cats.values()) if all_cats else 1
    for cat, ms in sorted(all_cats.items(), key=lambda x: -x[1]):
        pct = ms / grand_total_ms * 100 if grand_total_ms > 0 else 0
        color = C.RED if pct > 40 else C.YELLOW if pct > 15 else C.GREEN
        print(f"  {color}{cat:<20s}{C.RESET} {ms:>9,.0f}ms {pct:>6.1f}%  {bar(ms, max_cat, 30)}")

    # 가장 느린 턴 Top 10
    print(f"\n  {C.BOLD}가장 느린 턴 TOP 10{C.RESET}")
    all_turns = [(r.key, t) for r in results for t in r.turns]
    all_turns.sort(key=lambda x: -x[1].total_ms)

    print(f"  {'#':>3s} {'시나리오':<10s} {'턴':>3s} {'Step':<20s} {'총시간':>10s}  병목")
    print(f"  {'-'*3} {'-'*10} {'-'*3} {'-'*20} {'-'*10}  {'-'*25}")

    for i, (key, t) in enumerate(all_turns[:10]):
        cats = t.by_category()
        bottleneck = max(cats, key=cats.get) if cats else "-"
        bottleneck_ms = cats.get(bottleneck, 0)
        print(f"  {i+1:>3d} {key:<10s} {t.turn_num:>3d} {t.step_id:<20s} {t.total_ms:>9,.0f}ms  {bottleneck}={bottleneck_ms:,.0f}ms")

    # 가장 느린 개별 연산 Top 10
    print(f"\n  {C.BOLD}가장 느린 개별 연산 TOP 10{C.RESET}")
    all_records = [(r.key, t.turn_num, rec) for r in results for t in r.turns for rec in t.records]
    all_records.sort(key=lambda x: -x[2].duration_ms)

    print(f"  {'#':>3s} {'시나리오':<10s} {'턴':>3s} {'카테고리':<15s} {'연산':<35s} {'시간':>10s}")
    print(f"  {'-'*3} {'-'*10} {'-'*3} {'-'*15} {'-'*35} {'-'*10}")

    for i, (key, turn_num, rec) in enumerate(all_records[:10]):
        op = rec.operation[:35]
        print(f"  {i+1:>3d} {key:<10s} {turn_num:>3d} {rec.category:<15s} {op:<35s} {rec.duration_ms:>9,.0f}ms")

    # 병목 분석 요약
    print(f"\n  {C.BOLD}{C.RED}병목 분석{C.RESET}")

    sorted_cats = sorted(all_cats.items(), key=lambda x: -x[1])
    if sorted_cats:
        top_cat, top_ms = sorted_cats[0]
        top_pct = top_ms / grand_total_ms * 100 if grand_total_ms > 0 else 0
        print(f"  1. 최대 병목: {C.RED}{top_cat}{C.RESET} ({top_ms:,.0f}ms, {top_pct:.1f}%)")

    if len(sorted_cats) > 1:
        sec_cat, sec_ms = sorted_cats[1]
        sec_pct = sec_ms / grand_total_ms * 100 if grand_total_ms > 0 else 0
        print(f"  2. 차순위: {C.YELLOW}{sec_cat}{C.RESET} ({sec_ms:,.0f}ms, {sec_pct:.1f}%)")

    # 턴당 평균 분해
    print(f"\n  {C.BOLD}턴당 평균 시간 분해{C.RESET}")
    for cat, ms in sorted_cats:
        avg_per_turn = ms / grand_total_turns if grand_total_turns > 0 else 0
        print(f"    {cat:<20s}: 평균 {avg_per_turn:>7,.0f}ms/턴")
    print(f"    {'합계':<20s}: 평균 {grand_avg:>7,.0f}ms/턴")


def export_csv(results: list[ScenarioResult], filepath: str):
    """결과를 CSV로 내보내기"""
    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "scenario", "scenario_name", "turn_num", "step_id",
            "total_ms", "neo4j_ms", "llm_ms", "embedding_ms",
            "neo4j_embed_ms", "logic_ms", "utterance"
        ])
        for r in results:
            for t in r.turns:
                cats = t.by_category()
                writer.writerow([
                    r.key, r.name, t.turn_num, t.step_id,
                    round(t.total_ms, 1),
                    round(cats.get("neo4j", 0), 1),
                    round(cats.get("llm", 0), 1),
                    round(cats.get("embedding", 0), 1),
                    round(cats.get("neo4j+embed", 0), 1),
                    round(cats.get("logic", 0), 1),
                    t.utterance[:100],
                ])
    print(f"\n  CSV 내보내기: {filepath}")


# =============================================================================
# Main
# =============================================================================

def main():
    parser = argparse.ArgumentParser(description="SC301 테스트 시나리오 벤치마크")
    parser.add_argument("--db", choices=["local", "aura"], default="local")
    parser.add_argument("-s", "--scenario", help="시나리오 키 (p1std, p1lf, p2a, p2b, p3, p4abroad, p4semi, p5, all)")
    parser.add_argument("--no-cache", action="store_true", help="턴마다 캐시 클리어")
    parser.add_argument("--csv", metavar="FILE", help="결과 CSV 파일 경로")
    args = parser.parse_args()

    # 인프라 초기화
    config = CoreConfig.from_env(db_mode=args.db)
    core = InstrumentedCore(config)

    slot_model = os.environ.get("SLOT_EXTRACTION_MODEL")
    engine = InstrumentedFlowEngine(
        driver=core.driver,
        openai_client=core.openai,
        chat_model=core.config.openai_chat_model,
        async_openai_client=core.async_openai,
        slot_extraction_model=slot_model,
    )

    print(f"\n  {C.BOLD}SC301 시나리오 벤치마크{C.RESET}")
    print(f"  DB: {args.db.upper()}, 캐시: {'OFF' if args.no_cache else 'ON'}")
    print(f"  Chat Model: {config.openai_chat_model}")
    print(f"  Slot Model: {engine.slot_extraction_model}")

    # 시나리오 결정
    if args.scenario and args.scenario != "all":
        if args.scenario not in TEST_SCENARIOS:
            print(f"  알 수 없는 시나리오: {args.scenario}")
            print(f"  사용 가능: {', '.join(TEST_SCENARIOS.keys())}")
            sys.exit(1)
        keys = [args.scenario]
    else:
        keys = list(TEST_SCENARIOS.keys())

    # 실행
    results: list[ScenarioResult] = []
    for key in keys:
        engine.clear_cache()
        r = run_scenario_benchmark(engine, core, key, disable_cache=args.no_cache)
        results.append(r)

    # 요약
    print_summary(results)

    # CSV 내보내기
    if args.csv:
        export_csv(results, args.csv)

    core.close()


if __name__ == "__main__":
    main()
