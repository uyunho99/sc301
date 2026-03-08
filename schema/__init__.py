"""
schema/ - Neo4j 스키마, Cypher 쿼리, 비즈니스 룰 패키지

하위 호환: 기존 `from schema import X` 구문이 그대로 작동.
"""
from .queries import *          # noqa: F401,F403
from .ingestion import *        # noqa: F401,F403
from .branching_rules import *  # noqa: F401,F403
from .rule_conditions import *  # noqa: F401,F403
from .guide_rules import *      # noqa: F401,F403
from .slot_rules import *       # noqa: F401,F403
from .consultation_config import *  # noqa: F401,F403
