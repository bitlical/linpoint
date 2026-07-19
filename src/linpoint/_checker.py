from __future__ import annotations

import time
from dataclasses import dataclass
from enum import Enum
from typing import TypeVar

from ._history import Call, History
from ._model import Model

State = TypeVar("State")


class CheckStatus(Enum):
    LINEARIZABLE = "linearizable"
    NON_LINEARIZABLE = "non_linearizable"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class CheckResult:
    status: CheckStatus
    linearization: tuple[Call, ...] | None
    longest_prefix: tuple[Call, ...]
    explored_states: int


class _TimedOut(Exception):
    pass


def check_history(
    model: Model[State], history: History, *, timeout: float | None = None
) -> CheckResult:
    """Determine whether a completed history can satisfy a sequential model."""

    calls = history.calls
    all_done = (1 << len(calls)) - 1
    predecessors = [0] * len(calls)
    for current_index, current in enumerate(calls):
        for prior_index, prior in enumerate(calls):
            if prior.returned_at < current.invoked_at:
                predecessors[current_index] |= 1 << prior_index

    deadline = None if timeout is None else time.monotonic() + max(timeout, 0.0)
    seen: set[tuple[int, object]] = set()
    longest: tuple[Call, ...] = ()
    explored = 0

    def search(
        state: State, completed: int, path: tuple[Call, ...]
    ) -> tuple[Call, ...] | None:
        nonlocal explored, longest
        if deadline is not None and time.monotonic() >= deadline:
            raise _TimedOut
        explored += 1
        if len(path) > len(longest):
            longest = path
        if completed == all_done:
            return path

        if model.state_key is not None:
            key = (completed, model.state_key(state))
            if key in seen:
                return None
            seen.add(key)

        for index, call in enumerate(calls):
            bit = 1 << index
            if completed & bit or predecessors[index] & ~completed:
                continue
            legal, next_state = model.step(state, call.command, call.outcome)
            if not legal:
                continue
            result = search(next_state, completed | bit, (*path, call))
            if result is not None:
                return result
        return None

    try:
        linearization = search(model.initial(), 0, ())
    except _TimedOut:
        return CheckResult(CheckStatus.UNKNOWN, None, longest, explored)

    if linearization is None:
        return CheckResult(CheckStatus.NON_LINEARIZABLE, None, longest, explored)
    return CheckResult(CheckStatus.LINEARIZABLE, linearization, longest, explored)
