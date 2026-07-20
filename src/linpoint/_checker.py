from __future__ import annotations

import math
import time
from collections.abc import Sequence
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

    if timeout is not None and (timeout < 0 or not math.isfinite(timeout)):
        raise ValueError("timeout must be finite and non-negative")

    calls = history.calls
    if not calls:
        return CheckResult(CheckStatus.LINEARIZABLE, (), (), 1)

    deadline = None if timeout is None else time.monotonic() + max(timeout, 0.0)
    if deadline is not None and time.monotonic() >= deadline:
        return CheckResult(CheckStatus.UNKNOWN, None, (), 0)

    call_count = len(calls)
    invoked_order: Sequence[int] = range(call_count)
    calls_in_invocation_order = True
    for position in range(1, call_count):
        if calls[position - 1].invoked_at > calls[position].invoked_at:
            invoked_order = sorted(
                range(call_count), key=lambda index: calls[index].invoked_at
            )
            calls_in_invocation_order = False
            break

    forced_order = True
    for position in range(1, call_count):
        if (
            calls[invoked_order[position - 1]].returned_at
            >= calls[invoked_order[position]].invoked_at
        ):
            forced_order = False
            break

    # Non-overlapping calls have exactly one legal real-time ordering.
    if forced_order:
        state = model.initial()
        step = model.step
        explored = 1
        for prefix_length, index in enumerate(invoked_order):
            if deadline is not None and time.monotonic() >= deadline:
                return CheckResult(
                    CheckStatus.UNKNOWN,
                    None,
                    tuple(
                        calls[invoked_order[position]]
                        for position in range(prefix_length)
                    ),
                    explored,
                )
            call = calls[index]
            legal, state = step(state, call.command, call.outcome)
            if not legal:
                return CheckResult(
                    CheckStatus.NON_LINEARIZABLE,
                    None,
                    tuple(
                        calls[invoked_order[position]]
                        for position in range(prefix_length)
                    ),
                    explored,
                )
            if deadline is not None and time.monotonic() >= deadline:
                return CheckResult(
                    CheckStatus.UNKNOWN,
                    None,
                    tuple(
                        calls[invoked_order[position]]
                        for position in range(prefix_length)
                    ),
                    explored,
                )
            explored += 1
        result = (
            calls
            if calls_in_invocation_order
            else tuple(calls[index] for index in invoked_order)
        )
        return CheckResult(CheckStatus.LINEARIZABLE, result, result, explored)

    all_done = (1 << call_count) - 1
    predecessors = [0] * call_count
    returned_order: Sequence[int] = range(call_count)
    for position in range(1, call_count):
        if calls[position - 1].returned_at > calls[position].returned_at:
            returned_order = sorted(
                range(call_count), key=lambda index: calls[index].returned_at
            )
            break
    returned_mask = 0
    returned_cursor = 0
    for current_index in invoked_order:
        if deadline is not None and time.monotonic() >= deadline:
            return CheckResult(CheckStatus.UNKNOWN, None, (), 0)
        while (
            returned_cursor < call_count
            and calls[returned_order[returned_cursor]].returned_at
            < calls[current_index].invoked_at
        ):
            returned_mask |= 1 << returned_order[returned_cursor]
            returned_cursor += 1
        predecessors[current_index] = returned_mask

    seen: set[tuple[int, object]] = set()
    # Delay copying the deepest path until DFS is about to discard it.
    longest: list[int] = []
    longest_length = 0
    explored = 0
    path: list[int] = []
    stack_states: list[State] = []
    stack_completed: list[int] = []
    stack_remaining: list[int] = []
    state_key = model.state_key
    step = model.step

    try:
        initial_state = model.initial()
        if deadline is not None and time.monotonic() >= deadline:
            raise _TimedOut
        if state_key is not None:
            seen.add((0, state_key(initial_state)))
        elif type(initial_state).__hash__ is not object.__hash__:
            try:  # noqa: SIM105 - avoid a context manager in the checker hot path
                seen.add((0, initial_state))
            except TypeError:
                pass
        explored = 1
        stack_states.append(initial_state)
        stack_completed.append(0)
        stack_remaining.append(all_done)

        while stack_states:
            state = stack_states[-1]
            completed = stack_completed[-1]
            remaining = stack_remaining[-1]
            while remaining:
                if deadline is not None and time.monotonic() >= deadline:
                    raise _TimedOut
                bit = remaining & -remaining
                remaining ^= bit
                stack_remaining[-1] = remaining
                index = bit.bit_length() - 1
                if predecessors[index] & ~completed:
                    continue
                call = calls[index]
                legal, next_state = step(state, call.command, call.outcome)
                if not legal:
                    continue

                path.append(index)
                next_completed = completed | bit
                if deadline is not None and time.monotonic() >= deadline:
                    raise _TimedOut
                if len(path) > longest_length:
                    longest_length = len(path)
                if next_completed == all_done:
                    explored += 1
                    linearized_calls = tuple(calls[index] for index in path)
                    return CheckResult(
                        CheckStatus.LINEARIZABLE,
                        linearized_calls,
                        linearized_calls,
                        explored,
                    )

                duplicate = False
                if state_key is not None:
                    key = (next_completed, state_key(next_state))
                    if key in seen:
                        duplicate = True
                    else:
                        seen.add(key)
                elif type(next_state).__hash__ is not object.__hash__:
                    key = (next_completed, next_state)
                    try:
                        if key in seen:
                            duplicate = True
                        else:
                            seen.add(key)
                    except TypeError:
                        pass

                if duplicate:
                    if len(longest) < longest_length:
                        longest = path.copy()
                    path.pop()
                    continue

                explored += 1
                stack_states.append(next_state)
                stack_completed.append(next_completed)
                stack_remaining.append(all_done ^ next_completed)
                break
            else:
                stack_states.pop()
                stack_completed.pop()
                stack_remaining.pop()
                if path:
                    if len(longest) < longest_length:
                        longest = path.copy()
                    path.pop()
    except _TimedOut:
        if len(longest) < longest_length:
            longest = path.copy()
        return CheckResult(
            CheckStatus.UNKNOWN,
            None,
            tuple(calls[index] for index in longest),
            explored,
        )

    if len(longest) < longest_length:
        longest = path.copy()
    return CheckResult(
        CheckStatus.NON_LINEARIZABLE,
        None,
        tuple(calls[index] for index in longest),
        explored,
    )
