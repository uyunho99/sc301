"""
Hospital-specific plugin registry.

Compute functions are registered here and looked up by name from YAML config.
Each function signature: (state, context) -> Any | None
  - state: ConversationState (read slot values)
  - context: dict with {"lookup_tables": {...}, ...} from config
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

# type alias for compute functions
ComputeFunc = Callable[..., Optional[Any]]

COMPUTE_REGISTRY: dict[str, ComputeFunc] = {}


def register_compute(name: str):
    """Decorator to register a compute function by name."""
    def decorator(fn: ComputeFunc) -> ComputeFunc:
        COMPUTE_REGISTRY[name] = fn
        logger.debug("Registered compute function: %s", name)
        return fn
    return decorator


def load_default_plugins():
    """Load built-in compute plugins (triggers registration via import)."""
    from . import compute  # noqa: F401
