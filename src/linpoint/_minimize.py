from __future__ import annotations

import math
from typing import TypeVar

from ._checker import CheckResult, CheckStatus, check_history
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

    minimal, _ = _minimize_non_linearizable(model, history, result, timeout=timeout)
    return minimal


def _minimize_non_linearizable(
    model: Model[State],
    history: History,
    result: CheckResult,
    *,
    timeout: float | None = None,
) -> tuple[History, CheckResult]:
    """Minimize a history already proven to be non-linearizable."""

    calls = history.calls
    granularity = 2
    while len(calls) >= 2:
        chunk_size = math.ceil(len(calls) / granularity)
        reduced = False
        for start in range(0, len(calls), chunk_size):
            candidate = History(calls[:start] + calls[start + chunk_size :])
            candidate_result = check_history(model, candidate, timeout=timeout)
            if candidate_result.status is CheckStatus.NON_LINEARIZABLE:
                calls = candidate.calls
                result = candidate_result
                granularity = max(granularity - 1, 2)
                reduced = True
                break

        if reduced:
            continue
        if granularity >= len(calls):
            break
        granularity = min(len(calls), granularity * 2)

    return History(calls), result
