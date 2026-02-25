"""Intent dispatcher — registry-dict pattern (Architect spec #1)."""

from typing import Optional

from routers.chat_intents import (
    health,
    resources,
    metrics,
    operations,
    knowledge,
    rca,
    sop,
    ui_actions,
)
from routers.deps import logger

# Registry dict — add new domains here, no if/elif chain needed.
# Order matters: more-specific handlers first so patterns like 'rca deep'
# match before generic operations patterns.  SOP before resources so
# 'sop list' doesn't accidentally match the 'list' resource handler.
INTENT_HANDLERS = {
    "health": health.handle,
    "metrics": metrics.handle,
    "rca": rca.handle,
    "sop": sop.handle,
    "knowledge": knowledge.handle,
    "operations": operations.handle,
    "resources": resources.handle,
    "ui_actions": ui_actions.handle,
}


async def dispatch(message: str, message_lower: str) -> Optional[str]:
    """Try each intent handler in priority order.

    Returns the first non-None response, or None if no handler matched.
    Each handler catches its own domain-specific exceptions (Architect spec #3).
    The caller (chat.py) handles unexpected errors at the router level.
    """
    for _name, handler in INTENT_HANDLERS.items():
        try:
            result = await handler(message, message_lower)
            if result is not None:
                return result
        except Exception as exc:
            # Unexpected error inside a handler — log and continue to next
            logger.error("chat_intents.%s error: %s", _name, exc, exc_info=True)
            return f"❌ Internal error in {_name} handler: {exc}"
    return None
