from __future__ import annotations

from typing import TypeVar

from ._checker import CheckStatus, check_history
from ._history import History
from ._model import Model

State = TypeVar("State")


def minimize_history(
    model: Model[State], history: History, *, timeout: float | None = None
) -> History:
    """Remove calls until no single remaining call can be removed."""

    result = check_history(model, history, timeout=timeout)
    if result.status is not CheckStatus.NON_LINEARIZABLE:
        raise ValueError("only a non-linearizable history can be minimized")

    calls = list(history.calls)
    index = 0
    while index < len(calls):
        candidate = History((*calls[:index], *calls[index + 1 :]))
        result = check_history(model, candidate, timeout=timeout)
        if result.status is CheckStatus.NON_LINEARIZABLE:
            calls = list(candidate.calls)
            index = 0
        else:
            index += 1
    return History(tuple(calls))
