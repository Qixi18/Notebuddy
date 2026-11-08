"""Task cancellation checkpoints at every non-streaming provider request."""
from collections.abc import Callable
from contextlib import contextmanager
from contextvars import ContextVar

_checkpoint: ContextVar[Callable[[], None] | None] = ContextVar('provider_checkpoint', default=None)


@contextmanager
def request_checkpoint(check: Callable[[], None]):
    previous = _checkpoint.get()
    def combined():
        if previous:
            previous()
        check()
    token = _checkpoint.set(combined)
    try:
        yield
    finally:
        _checkpoint.reset(token)


def check_request_allowed() -> None:
    check = _checkpoint.get()
    if check:
        check()
