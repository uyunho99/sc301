"""
state.py - 세션 상태 관리

대화 세션의 상태를 저장/관리하는 데이터 클래스.
slots, current_step, persona, scenario 등을 추적.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any
import json
import os
from datetime import datetime


@dataclass
class ConversationState:
    """대화 세션 상태를 관리하는 클래스"""
    
    session_id: str
    persona_id: str | None = None
    scenario_id: str | None = None
    current_step_id: str | None = None
    slots: dict[str, Any] = field(default_factory=dict)
    history: list[dict] = field(default_factory=list)
    step_turn_count: int = 0
    step_history: list[str] = field(default_factory=list)
    prefetch_slots: dict[str, Any] = field(default_factory=dict)
    persona_disambiguation: dict | None = None
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())
    
    # --- Slot 관련 메서드 ---
    
    def get_slot(self, var_name: str, default: Any = None) -> Any:
        """특정 slot 값 조회"""
        return self.slots.get(var_name, default)
    
    def set_slot(self, var_name: str, value: Any) -> None:
        """slot 값 설정"""
        self.slots[var_name] = value
        self._touch()
    
    def is_slot_filled(self, var_name: str) -> bool:
        """slot이 채워졌는지 확인 (None, 빈 문자열, "null" 문자열, 빈 dict/list 제외)"""
        if var_name not in self.slots:
            return False
        value = self.slots[var_name]
        if value is None:
            return False
        if isinstance(value, str) and not value.strip():
            return False
        if isinstance(value, str) and value.strip().lower() == "null":
            return False
        if isinstance(value, (dict, list)) and len(value) == 0:
            return False
        return True
    
    def get_filled_slots(self) -> dict[str, Any]:
        """채워진 slot들만 반환 (is_slot_filled 기준과 일치)"""
        return {k: v for k, v in self.slots.items() if self.is_slot_filled(k)}

    # --- Prefetch Slot 관련 메서드 ---

    def set_prefetch_slot(self, var_name: str, value: Any) -> None:
        """prefetch slot 설정 (다음 스텝용, 현재 스텝에서는 미수집 취급)"""
        self.prefetch_slots[var_name] = value
        self._touch()

    def promote_prefetch_slots(self) -> dict[str, Any]:
        """prefetch → 정식 slots 승격 (스텝 전이 시 호출).
        이미 정식으로 채워진 슬롯은 덮어쓰지 않음.
        Returns: 승격된 슬롯 딕셔너리"""
        promoted = {}
        for k, v in self.prefetch_slots.items():
            if not self.is_slot_filled(k):
                self.slots[k] = v
                promoted[k] = v
        self.prefetch_slots.clear()
        self._touch()
        return promoted
    
    # --- History 관련 메서드 ---
    
    def add_turn(self, role: str, content: str, metadata: dict | None = None) -> None:
        """대화 턴 추가"""
        turn = {
            "role": role,
            "content": content,
            "timestamp": datetime.now().isoformat(),
        }
        if metadata:
            turn["metadata"] = metadata
        self.history.append(turn)
        self._touch()
    
    def get_recent_history(self, n: int = 10) -> list[dict]:
        """최근 n개 턴 반환"""
        return self.history[-n:] if len(self.history) > n else self.history
    
    def get_history_as_messages(self, n: int = 6) -> list[dict]:
        """OpenAI messages 형식으로 변환 (전략 8: 기본값 10 → 6으로 축소)"""
        return [
            {"role": t["role"], "content": t["content"]}
            for t in self.get_recent_history(n)
        ]

    # --- Step 관련 메서드 ---
    
    def move_to_step(self, step_id: str) -> None:
        """현재 step 변경"""
        if self.current_step_id:
            self.step_history.append(self.current_step_id)
        self.current_step_id = step_id
        self.step_turn_count = 0  # 새 스텝으로 이동 시 턴 카운터 리셋
        self._touch()

    def increment_step_turn(self) -> int:
        """현재 스텝 턴 카운터 증가. 새 카운트 반환."""
        self.step_turn_count += 1
        return self.step_turn_count
    
    def is_started(self) -> bool:
        """시나리오가 시작되었는지 확인"""
        return self.scenario_id is not None and self.current_step_id is not None
    
    # --- 직렬화 메서드 ---
    
    def to_dict(self) -> dict:
        """딕셔너리로 변환 (저장용)"""
        return {
            "session_id": self.session_id,
            "persona_id": self.persona_id,
            "scenario_id": self.scenario_id,
            "current_step_id": self.current_step_id,
            "slots": self.slots,
            "prefetch_slots": self.prefetch_slots,
            "history": self.history,
            "step_turn_count": self.step_turn_count,
            "step_history": self.step_history,
            "persona_disambiguation": self.persona_disambiguation,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ConversationState":
        """딕셔너리에서 생성"""
        return cls(
            session_id=data["session_id"],
            persona_id=data.get("persona_id"),
            scenario_id=data.get("scenario_id"),
            current_step_id=data.get("current_step_id"),
            slots=data.get("slots", {}),
            prefetch_slots=data.get("prefetch_slots", {}),
            history=data.get("history", []),
            step_turn_count=data.get("step_turn_count", 0),
            step_history=data.get("step_history", []),
            persona_disambiguation=data.get("persona_disambiguation"),
            created_at=data.get("created_at", datetime.now().isoformat()),
            updated_at=data.get("updated_at", datetime.now().isoformat()),
        )
    
    def to_json(self) -> str:
        """JSON 문자열로 변환"""
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)
    
    @classmethod
    def from_json(cls, json_str: str) -> "ConversationState":
        """JSON 문자열에서 생성"""
        return cls.from_dict(json.loads(json_str))
    
    # --- 내부 헬퍼 ---
    
    def _touch(self) -> None:
        """updated_at 갱신"""
        self.updated_at = datetime.now().isoformat()


class StateStorage:
    """상태 저장소 추상 클래스"""
    
    def save(self, state: ConversationState) -> None:
        raise NotImplementedError
    
    def load(self, session_id: str) -> ConversationState | None:
        raise NotImplementedError
    
    def exists(self, session_id: str) -> bool:
        raise NotImplementedError
    
    def delete(self, session_id: str) -> None:
        raise NotImplementedError


class FileStateStorage(StateStorage):
    """파일 기반 상태 저장소"""
    
    def __init__(self, storage_dir: str = "./states"):
        self.storage_dir = storage_dir
        os.makedirs(storage_dir, exist_ok=True)
    
    def _get_path(self, session_id: str) -> str:
        return os.path.join(self.storage_dir, f"{session_id}.json")
    
    def save(self, state: ConversationState) -> None:
        path = self._get_path(state.session_id)
        with open(path, "w", encoding="utf-8") as f:
            f.write(state.to_json())
    
    def load(self, session_id: str) -> ConversationState | None:
        path = self._get_path(session_id)
        if not os.path.exists(path):
            return None
        with open(path, "r", encoding="utf-8") as f:
            return ConversationState.from_json(f.read())
    
    def exists(self, session_id: str) -> bool:
        return os.path.exists(self._get_path(session_id))
    
    def delete(self, session_id: str) -> None:
        path = self._get_path(session_id)
        if os.path.exists(path):
            os.remove(path)
    
    def list_sessions(self) -> list[str]:
        """저장된 모든 세션 ID 반환"""
        files = os.listdir(self.storage_dir)
        return [f.replace(".json", "") for f in files if f.endswith(".json")]


class RedisStateStorage(StateStorage):
    """Redis 기반 상태 저장소 (선택적)"""
    
    def __init__(self, redis_url: str, prefix: str = "sc301:state:"):
        try:
            import redis
            self.client = redis.from_url(redis_url)
            self.prefix = prefix
        except ImportError:
            raise ImportError("redis 패키지가 필요합니다: pip install redis")
    
    def _get_key(self, session_id: str) -> str:
        return f"{self.prefix}{session_id}"
    
    def save(self, state: ConversationState, ttl: int = 86400) -> None:
        """상태 저장 (기본 TTL: 24시간)"""
        key = self._get_key(state.session_id)
        self.client.setex(key, ttl, state.to_json())
    
    def load(self, session_id: str) -> ConversationState | None:
        key = self._get_key(session_id)
        data = self.client.get(key)
        if data is None:
            return None
        return ConversationState.from_json(data.decode("utf-8"))
    
    def exists(self, session_id: str) -> bool:
        return bool(self.client.exists(self._get_key(session_id)))
    
    def delete(self, session_id: str) -> None:
        self.client.delete(self._get_key(session_id))


def get_storage(backend: str = "file", **kwargs) -> StateStorage:
    """백엔드 타입에 따른 저장소 인스턴스 반환"""
    if backend == "file":
        return FileStateStorage(kwargs.get("storage_dir", "./states"))
    elif backend == "redis":
        redis_url = kwargs.get("redis_url")
        if not redis_url:
            raise ValueError("redis 백엔드는 redis_url이 필요합니다")
        return RedisStateStorage(redis_url)
    else:
        raise ValueError(f"지원하지 않는 백엔드: {backend}")
