from __future__ import annotations

import math
import time
from collections.abc import Iterator
from dataclasses import dataclass
from enum import Enum
from typing import TypeVar

from ._history import Call, History
from ._model import Model

State = TypeVar("State")
_UNCACHEABLE = object()


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

    if timeout is not None and (timeout < 0 or not math.isfinite(timeout)):
        raise ValueError("timeout must be finite and non-negative")

    calls = history.calls
    if not calls:
        return CheckResult(CheckStatus.LINEARIZABLE, (), (), 1)

    deadline = None if timeout is None else time.monotonic() + max(timeout, 0.0)
    if deadline is not None and time.monotonic() >= deadline:
        return CheckResult(CheckStatus.UNKNOWN, None, (), 0)

    all_done = (1 << len(calls)) - 1
    predecessors = [0] * len(calls)
    returned_order = sorted(
        range(len(calls)), key=lambda index: calls[index].returned_at
    )
    returned_mask = 0
    returned_cursor = 0
    for current_index in sorted(
        range(len(calls)), key=lambda index: calls[index].invoked_at
    ):
        if deadline is not None and time.monotonic() >= deadline:
            return CheckResult(CheckStatus.UNKNOWN, None, (), 0)
        while (
            returned_cursor < len(calls)
            and calls[returned_order[returned_cursor]].returned_at
            < calls[current_index].invoked_at
        ):
            returned_mask |= 1 << returned_order[returned_cursor]
            returned_cursor += 1
        predecessors[current_index] = returned_mask

    seen: set[tuple[int, object]] = set()
    longest: tuple[int, ...] = ()
    explored = 0
    path: list[int] = []
    stack: list[Iterator[tuple[int, State, int]]] = []

    def candidates(state: State, completed: int) -> Iterator[tuple[int, State, int]]:
        for index, call in enumerate(calls):
            if deadline is not None and time.monotonic() >= deadline:
                raise _TimedOut
            bit = 1 << index
            if completed & bit or predecessors[index] & ~completed:
                continue
            legal, next_state = model.step(state, call.command, call.outcome)
            if legal:
                yield index, next_state, completed | bit

    def enter(state: State, completed: int) -> bool | None:
        nonlocal explored, longest
        if deadline is not None and time.monotonic() >= deadline:
            raise _TimedOut
        if len(path) > len(longest):
            longest = tuple(path)
        if completed == all_done:
            explored += 1
            return True

        if model.state_key is not None:
            state_identity: object = model.state_key(state)
        else:
            try:
                hash(state)
            except TypeError:
                state_identity = _UNCACHEABLE
            else:
                state_identity = state

        if state_identity is not _UNCACHEABLE:
            key = (completed, state_identity)
            if key in seen:
                return False
            seen.add(key)

        explored += 1
        stack.append(candidates(state, completed))
        return None

    try:
        enter(model.initial(), 0)
        while stack:
            try:
                index, next_state, completed = next(stack[-1])
            except StopIteration:
                stack.pop()
                if path:
                    path.pop()
                continue

            path.append(index)
            entered = enter(next_state, completed)
            if entered is True:
                linearization = tuple(calls[index] for index in path)
                return CheckResult(
                    CheckStatus.LINEARIZABLE,
                    linearization,
                    linearization,
                    explored,
                )
            if entered is False:
                path.pop()
    except _TimedOut:
        return CheckResult(
            CheckStatus.UNKNOWN,
            None,
            tuple(calls[index] for index in longest),
            explored,
        )

    return CheckResult(
        CheckStatus.NON_LINEARIZABLE,
        None,
        tuple(calls[index] for index in longest),
        explored,
    )
