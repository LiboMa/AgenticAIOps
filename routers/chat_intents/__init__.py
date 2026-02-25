"""Intent dispatcher — registry-dict pattern (Architect spec #1)."""

from typing import Optional

from routers.chat_intents import (
    health,
    resources,
    metrics,
    operations,
    ui_actions,
)
from routers.deps import logger

# Registry dict — add new domains here, no if/elif chain needed.
INTENT_HANDLERS = {
    "health": health.handle,
    "resources": resources.handle,
    "metrics": metrics.handle,
    "operations": operations.handle,
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
