"""
cli.py - 명령줄 인터페이스

python -m sc301_layer.cli <command> 형식으로 실행.

Commands:
- setup-schema: Neo4j 스키마 설정
- ingest <ttl_path>: TTL 파일 적재
- turn <session_id> <user_text>: 단일 턴 실행
- repl <session_id>: 대화형 REPL 모드 (스트리밍 지원)
- health: 연결 상태 확인

모델 선택:
- 기본: gpt-4o (응답) + gpt-4o-mini (슬롯 추출)
- --model gpt-5: gpt-5 (응답) + gpt-5-mini (슬롯 추출)

최적화 내용:
- 전략 6: LLM 스트리밍 응답 (REPL 모드)
- 전략 4: 비동기 처리 (선택적)
"""

from __future__ import annotations

import argparse
import logging
import sys
import os
import uuid
import asyncio
from pathlib import Path

from dotenv import load_dotenv

# 환경변수 로드
load_dotenv()

try:
    from .core import Core, CoreConfig
    from .flow import FlowEngine
    from .state import ConversationState, get_storage
except ImportError:
    from core import Core, CoreConfig
    from flow import FlowEngine
    from state import ConversationState, get_storage

# 로깅 설정
logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger(__name__)

# Neo4j 경고 메시지 숨기기
logging.getLogger("neo4j.notifications").setLevel(logging.ERROR)
logging.getLogger("neo4j").setLevel(logging.ERROR)
logging.getLogger("httpx").setLevel(logging.ERROR)


def get_core(db_mode: str = "aura") -> Core:
    """Core 인스턴스 생성

    Args:
        db_mode: "aura" (Neo4j AuraDB) 또는 "local" (로컬 Neo4j)
    """
    config = CoreConfig.from_env(db_mode=db_mode)
    return Core(config)


MODEL_PRESETS = {
    "gpt-4o":  {"chat": "gpt-4o",  "slot": "gpt-4o-mini"},
    "gpt-5":   {"chat": "gpt-5",   "slot": "gpt-5-mini"},
}


def get_flow_engine(
    core: Core,
    fast_mode: bool = False,
    model_override: str | None = None,
) -> FlowEngine:
    """
    FlowEngine 인스턴스 생성 (비동기 클라이언트 포함)

    Args:
        core: Core 인스턴스
        fast_mode: True면 gpt-4o-mini로 slot 추출, 응답 토큰 제한 적용
        model_override: "gpt-4o" 또는 "gpt-5" — 지정 시 .env 설정 무시
    """
    # 모델 결정: --model 인자 > .env 값
    if model_override and model_override in MODEL_PRESETS:
        preset = MODEL_PRESETS[model_override]
        chat_model = preset["chat"]
        slot_model = preset["slot"]
    else:
        chat_model = core.config.openai_chat_model
        slot_model = os.environ.get("SLOT_EXTRACTION_MODEL")

    max_tokens_str = os.environ.get("MAX_RESPONSE_TOKENS", "500")

    # fast_mode면 gpt-4o-mini 강제 사용
    if fast_mode:
        slot_model = "gpt-4o-mini"
        max_tokens = 300  # 더 짧게
    else:
        max_tokens = int(max_tokens_str)

    return FlowEngine(
        driver=core.driver,
        openai_client=core.openai,
        chat_model=chat_model,
        async_openai_client=core.async_openai,
        slot_extraction_model=slot_model,
        max_response_tokens=max_tokens,
    )


def get_state_storage():
    """StateStorage 인스턴스 생성"""
    backend = os.environ.get("STATE_BACKEND", "file")
    storage_dir = os.environ.get("STATE_STORAGE_DIR", "./states")
    redis_url = os.environ.get("REDIS_URL")

    return get_storage(
        backend=backend,
        storage_dir=storage_dir,
        redis_url=redis_url
    )


# =============================================================================
# Commands
# =============================================================================

def cmd_setup_schema(args):
    """Neo4j 스키마 설정"""
    db_mode = args.db
    print(f"🔧 Neo4j 스키마 설정 중... (DB: {db_mode})")

    with get_core(db_mode) as core:
        core.ensure_schema()

    print("✅ 스키마 설정 완료")


def cmd_ingest(args):
    """TTL 파일 Neo4j에 적재"""
    ttl_path = args.ttl_path
    db_mode = args.db

    if not Path(ttl_path).exists():
        print(f"❌ 파일을 찾을 수 없습니다: {ttl_path}")
        sys.exit(1)

    print(f"📥 TTL 파일 적재 중: {ttl_path} (DB: {db_mode})")

    with get_core(db_mode) as core:
        stats = core.ingest_documents(
            ttl_path,
            create_embeddings=not args.no_embeddings
        )

    print("✅ 적재 완료:")
    for key, value in stats.items():
        print(f"  - {key}: {value}")


def cmd_turn(args):
    """단일 턴 실행"""
    session_id = args.session_id
    user_text = args.user_text
    db_mode = args.db
    model_override = getattr(args, "model", None)

    storage = get_state_storage()

    # State 로드 또는 생성
    state = storage.load(session_id)
    if not state:
        state = ConversationState(session_id=session_id)
        print(f"🆕 새 세션 생성: {session_id}")

    with get_core(db_mode) as core:
        flow = get_flow_engine(core, model_override=model_override)

        # 턴 처리
        response, state = flow.process_turn(state, user_text, core=core)

    # State 저장
    storage.save(state)

    print(f"\n👤 User: {user_text}")
    print(f"🤖 Bot: {response}")
    print(f"\n📍 Current Step: {state.current_step_id}")
    print(f"📝 Slots: {state.get_filled_slots()}")


def cmd_repl(args):
    """대화형 REPL 모드 (스트리밍 지원)"""
    session_id = args.session_id or str(uuid.uuid4())[:8]
    use_streaming = not args.no_streaming
    fast_mode = args.fast  # --fast 옵션
    db_mode = args.db
    model_override = getattr(args, "model", None)

    storage = get_state_storage()

    # State 로드 또는 생성
    state = storage.load(session_id)
    if not state:
        state = ConversationState(session_id=session_id)

    print(f"🚀 SC301 챗봇 REPL 시작 (세션: {session_id})")
    print(f"🗄️  Neo4j: {db_mode.upper()} 모드")
    if model_override:
        preset = MODEL_PRESETS[model_override]
        print(f"🤖 모델: 응답={preset['chat']}, 슬롯추출={preset['slot']}")
    else:
        print(f"🤖 모델: 응답={os.environ.get('OPENAI_CHAT_MODEL', 'gpt-4o')}, "
              f"슬롯추출={os.environ.get('SLOT_EXTRACTION_MODEL', 'gpt-4o-mini')}")
    if use_streaming:
        print("📡 스트리밍 모드 활성화")
    if fast_mode:
        print("⚡ Fast 모드 활성화 (gpt-4o-mini로 slot 추출)")
    print("종료하려면 'quit' 또는 'exit'를 입력하세요.\n")

    with get_core(db_mode) as core:
        flow = get_flow_engine(core, fast_mode=fast_mode, model_override=model_override)

        # 초기 메시지 (시나리오가 없으면)
        if not state.is_started():
            print("🤖 Bot: 안녕하세요! 성형외과 상담 챗봇입니다. 어떤 상담이 필요하신가요?\n")

        while True:
            try:
                user_input = input("👤 You: ").strip()

                if not user_input:
                    continue

                if user_input.lower() in ["quit", "exit", "q"]:
                    print("👋 상담을 종료합니다. 감사합니다!")
                    break

                if user_input.lower() == "/state":
                    # 디버그: 현재 상태 출력
                    print(f"\n📊 Current State:")
                    print(f"  Persona: {state.persona_id}")
                    print(f"  Scenario: {state.scenario_id}")
                    print(f"  Step: {state.current_step_id}")
                    print(f"  Slots: {state.get_filled_slots()}\n")
                    continue

                if user_input.lower() == "/reset":
                    # 세션 초기화
                    state = ConversationState(session_id=session_id)
                    storage.save(state)
                    print("🔄 세션이 초기화되었습니다.\n")
                    continue

                if user_input.lower() == "/cache":
                    # 캐시 상태 출력
                    print(f"\n📦 Cache Status:")
                    print(f"  Embedding cache: {len(core._embedding_cache)} items")
                    print(f"  Step cache: {len(flow._step_cache)} items")
                    print(f"  Persona cache: {len(flow._persona_cache)} items\n")
                    continue

                if user_input.lower() == "/clear-cache":
                    # 캐시 초기화
                    core.clear_embedding_cache()
                    flow.clear_cache()
                    print("🗑️ 캐시가 초기화되었습니다.\n")
                    continue

                # 턴 처리 (스트리밍 또는 일반)
                if use_streaming:
                    print("🤖 Bot: ", end="", flush=True)

                    response = ""
                    for item in flow.process_turn_streaming(state, user_input, core=core):
                        if isinstance(item, str):
                            print(item, end="", flush=True)
                            response += item
                        else:
                            # 마지막 반환값 (response, state)
                            response, state = item

                    print("\n")
                else:
                    response, state = flow.process_turn(state, user_input, core=core)
                    print(f"🤖 Bot: {response}\n")

                # State 저장
                storage.save(state)

            except KeyboardInterrupt:
                print("\n👋 상담을 종료합니다.")
                break
            except Exception as e:
                logger.error(f"오류 발생: {e}")
                print(f"❌ 오류가 발생했습니다: {e}\n")


def cmd_repl_async(args):
    """비동기 대화형 REPL 모드 (전략 4)"""
    asyncio.run(_repl_async(args))


async def _repl_async(args):
    """비동기 REPL 내부 구현"""
    session_id = args.session_id or str(uuid.uuid4())[:8]
    db_mode = args.db

    storage = get_state_storage()

    # State 로드 또는 생성
    state = storage.load(session_id)
    if not state:
        state = ConversationState(session_id=session_id)

    print(f"🚀 SC301 챗봇 비동기 REPL 시작 (세션: {session_id})")
    print(f"🗄️  Neo4j: {db_mode.upper()} 모드")
    print("종료하려면 'quit' 또는 'exit'를 입력하세요.\n")

    core = get_core(db_mode)
    flow = get_flow_engine(core)

    try:
        # 초기 메시지
        if not state.is_started():
            print("🤖 Bot: 안녕하세요! 성형외과 상담 챗봇입니다. 어떤 상담이 필요하신가요?\n")

        while True:
            try:
                # 비동기 입력 (실제로는 동기 input 사용)
                user_input = await asyncio.to_thread(input, "👤 You: ")
                user_input = user_input.strip()

                if not user_input:
                    continue

                if user_input.lower() in ["quit", "exit", "q"]:
                    print("👋 상담을 종료합니다. 감사합니다!")
                    break

                if user_input.lower() == "/state":
                    print(f"\n📊 Current State:")
                    print(f"  Persona: {state.persona_id}")
                    print(f"  Scenario: {state.scenario_id}")
                    print(f"  Step: {state.current_step_id}")
                    print(f"  Slots: {state.get_filled_slots()}\n")
                    continue

                if user_input.lower() == "/reset":
                    state = ConversationState(session_id=session_id)
                    storage.save(state)
                    print("🔄 세션이 초기화되었습니다.\n")
                    continue

                # 비동기 턴 처리
                response, state = await flow.process_turn_async(state, user_input, core=core)

                print(f"🤖 Bot: {response}\n")

                # State 저장
                storage.save(state)

            except KeyboardInterrupt:
                print("\n👋 상담을 종료합니다.")
                break
            except Exception as e:
                logger.error(f"오류 발생: {e}")
                print(f"❌ 오류가 발생했습니다: {e}\n")
    finally:
        core.close()


def cmd_health(args):
    """연결 상태 확인"""
    db_mode = args.db
    print(f"🏥 연결 상태 확인 중... (DB: {db_mode})")

    with get_core(db_mode) as core:
        status = core.health_check()

    for service, value in status.items():
        if isinstance(value, bool):
            emoji = "✅" if value else "❌"
            print(f"  {emoji} {service}: {'OK' if value else 'Failed'}")
        else:
            print(f"  📊 {service}: {value}")


def cmd_query(args):
    """임의의 Cypher 쿼리 실행 (디버그용)"""
    query = args.query
    db_mode = args.db

    with get_core(db_mode) as core:
        results = core.run_query(query)

    print(f"\n📊 Results ({len(results)} rows):")
    for r in results[:20]:  # 최대 20개만 출력
        print(f"  {r}")

    if len(results) > 20:
        print(f"  ... and {len(results) - 20} more rows")


def cmd_list_sessions(args):
    """저장된 세션 목록"""
    storage = get_state_storage()

    if hasattr(storage, "list_sessions"):
        sessions = storage.list_sessions()
        print(f"📋 저장된 세션 ({len(sessions)}개):")
        for sid in sessions:
            state = storage.load(sid)
            if state:
                print(f"  - {sid}: step={state.current_step_id}, slots={len(state.slots)}")
    else:
        print("⚠️ 현재 스토리지는 목록 조회를 지원하지 않습니다.")


# =============================================================================
# Main
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        prog="sc301_layer",
        description="SC301 Graph RAG 챗봇 CLI"
    )

    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # 공통 --db, --model 옵션을 위한 부모 parser
    db_parent = argparse.ArgumentParser(add_help=False)
    db_parent.add_argument(
        "--db", choices=["aura", "local"], default="aura",
        help="Neo4j DB 모드: aura (AuraDB 클라우드) 또는 local (로컬 Neo4j) (기본값: aura)"
    )
    db_parent.add_argument(
        "--model", choices=["gpt-4o", "gpt-5"], default=None,
        help="LLM 모델 선택 (기본: .env 설정값 gpt-4o)"
    )

    # setup-schema
    sub_schema = subparsers.add_parser("setup-schema", parents=[db_parent], help="Neo4j 스키마 설정")
    sub_schema.set_defaults(func=cmd_setup_schema)

    # ingest
    sub_ingest = subparsers.add_parser("ingest", parents=[db_parent], help="TTL 파일 적재")
    sub_ingest.add_argument("ttl_path", help="TTL 파일 경로")
    sub_ingest.add_argument("--no-embeddings", action="store_true", help="임베딩 생성 스킵")
    sub_ingest.set_defaults(func=cmd_ingest)

    # turn
    sub_turn = subparsers.add_parser("turn", parents=[db_parent], help="단일 턴 실행")
    sub_turn.add_argument("session_id", help="세션 ID")
    sub_turn.add_argument("user_text", help="사용자 입력")
    sub_turn.set_defaults(func=cmd_turn)

    # repl
    sub_repl = subparsers.add_parser("repl", parents=[db_parent], help="대화형 REPL 모드")
    sub_repl.add_argument("session_id", nargs="?", help="세션 ID (생략시 자동 생성)")
    sub_repl.add_argument("--no-streaming", action="store_true", help="스트리밍 비활성화")
    sub_repl.add_argument("--fast", action="store_true", help="Fast 모드 (gpt-4o-mini로 slot 추출, 응답 길이 제한)")
    sub_repl.set_defaults(func=cmd_repl)

    # repl-async
    sub_repl_async = subparsers.add_parser("repl-async", parents=[db_parent], help="비동기 대화형 REPL 모드")
    sub_repl_async.add_argument("session_id", nargs="?", help="세션 ID (생략시 자동 생성)")
    sub_repl_async.set_defaults(func=cmd_repl_async)

    # health
    sub_health = subparsers.add_parser("health", parents=[db_parent], help="연결 상태 확인")
    sub_health.set_defaults(func=cmd_health)

    # query (디버그)
    sub_query = subparsers.add_parser("query", parents=[db_parent], help="Cypher 쿼리 실행 (디버그)")
    sub_query.add_argument("query", help="Cypher 쿼리")
    sub_query.set_defaults(func=cmd_query)

    # sessions
    sub_sessions = subparsers.add_parser("sessions", help="저장된 세션 목록")
    sub_sessions.set_defaults(func=cmd_list_sessions)

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(1)

    args.func(args)


if __name__ == "__main__":
    main()
