"""Request-local demo tenant. Never mutate global settings to switch views."""
from contextlib import contextmanager
from contextvars import ContextVar

DEMO_DATASET = 'agent_quality_demo'
_ACTIVE = ContextVar('feedback_role_demo_active',default=False)


def is_demo() -> bool:
    return _ACTIVE.get()


@contextmanager
def demo_scope():
    token=_ACTIVE.set(True)
    try:yield
    finally:_ACTIVE.reset(token)
