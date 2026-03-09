"""
schema/ - Neo4j 스키마, Cypher 쿼리 패키지

순수 Cypher 쿼리만 포함. 비즈니스 규칙은 config/ 패키지로 이동.
하위 호환: 기존 `from schema import X` 구문이 그대로 작동하도록 config/ 재수출.
"""
from .queries import *    # noqa: F401,F403
from .ingestion import *  # noqa: F401,F403

# 하위 호환: config/로 이동한 비즈니스 규칙 재수출
try:
    from ..config import *  # noqa: F401,F403
except ImportError:
    from config import *    # noqa: F401,F403
