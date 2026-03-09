"""
config/ - 비즈니스 규칙 & 설정 패키지

분기 규칙, 조건 매핑, Guide 선택, 슬롯 규칙, 상담 설정 등
Flow 로직에서 사용하는 정적 설정을 모아둔 패키지.
"""
from .branching import *    # noqa: F401,F403
from .conditions import *   # noqa: F401,F403
from .guides import *       # noqa: F401,F403
from .slots import *        # noqa: F401,F403
from .consultation import * # noqa: F401,F403
