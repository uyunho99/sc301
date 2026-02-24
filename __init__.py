"""
sc301_layer - Graph RAG 챗봇 프레임워크

성형외과 상담 시나리오를 위한 Graph RAG 기반 대화 시스템.
Neo4j AuraDB + OpenAI + TTL 온톨로지 기반 플로우 엔진.
"""

__version__ = "0.1.0"

from .state import ConversationState
from .core import Core
from .flow import FlowEngine

__all__ = [
    "ConversationState",
    "Core", 
    "FlowEngine",
    "__version__",
]
