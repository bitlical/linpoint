from __future__ import annotations

import math
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from functools import lru_cache
from types import CodeType, FrameType
from typing import Any, Literal, TypeAlias

from ._history import Call, Command, History, Outcome, Raised, Returned

Scheduling: TypeAlias = Literal["native", "stress"]
_STRESS_SYNC_LINES = 64
_STRESS_SYNC_TIMEOUT = 0.001
_STRESS_YIELD_OPCODES = 64


@lru_cache(maxsize=128)
def _should_yield_opcodes(code: CodeType) -> bool:
    body_line: int | None = None
    for _, _, line in code.co_lines():
        if line is None or line == code.co_firstlineno:
            continue
        if body_line is None:
            body_line = line
        elif line != body_line:
            return False
    return True


class RunTimedOut(TimeoutError):
    """Raised when one or more scenario threads exceed the execution timeout."""

    def __init__(self, history: History, active_threads: tuple[int, ...]) -> None:
        self.history = history
        self.active_threads = active_threads
        thread_list = ", ".join(map(str, active_threads)) or "unknown"
        super().__init__(f"scenario execution timed out; active threads: {thread_list}")


@dataclass(frozen=True, slots=True)
class Scenario:
    """Commands assigned to each participating thread."""

    threads: tuple[tuple[Command, ...], ...]

    def __post_init__(self) -> None:
        threads = self.threads
        normalized = type(threads) is tuple
        if normalized:
            for commands in threads:
                if type(commands) is not tuple:
                    normalized = False
                    break
        if not normalized:
            threads = tuple(tuple(commands) for commands in threads)
        if not threads:
            raise ValueError("a scenario must contain at least one thread")
        if not any(threads):
            raise ValueError("a scenario must contain at least one command")
        object.__setattr__(self, "threads", threads)


def run(
    implementation: Callable[[], Any],
    scenario: Scenario,
    *,
    timeout: float | None = None,
    scheduling: Scheduling = "stress",
) -> History:
    """Execute a scenario against one shared implementation instance."""

    if timeout is not None and (timeout < 0 or not math.isfinite(timeout)):
        raise ValueError("timeout must be finite and non-negative")
    if scheduling not in ("native", "stress"):
        raise ValueError("scheduling must be 'native' or 'stress'")

    subject = implementation()
    deadline = None if timeout is None else time.monotonic() + timeout
    start_gate = threading.Barrier(len(scenario.threads) + 1)
    event_lock = threading.Lock()
    calls: list[Call | None] = []
    worker_errors: list[BaseException] = []
    next_event = 0
    if scheduling == "stress":
        round_parties = tuple(
            sum(len(commands) > round_index for commands in scenario.threads)
            for round_index in range(max(map(len, scenario.threads)))
        )
        round_gates = tuple(threading.Barrier(parties) for parties in round_parties)
        line_gates = tuple(threading.Barrier(parties) for parties in round_parties)
        stress_enabled = any(parties > 1 for parties in round_parties)
    else:
        round_gates = ()
        line_gates = ()
        stress_enabled = False

    def record_invocation() -> tuple[int, int]:
        nonlocal next_event
        with event_lock:
            event = next_event
            next_event += 1
            slot = len(calls)
            calls.append(None)
            return event, slot

    def record_return(
        thread_id: int,
        command: Command,
        outcome: Outcome,
        invoked_at: int,
        slot: int,
    ) -> None:
        nonlocal next_event
        with event_lock:
            returned_at = next_event
            next_event += 1
            calls[slot] = Call(thread_id, command, outcome, invoked_at, returned_at)

    def native_worker(thread_id: int, commands: tuple[Command, ...]) -> None:
        try:
            start_gate.wait()
            for command in commands:
                method: Callable[..., Any] = getattr(subject, command.name)
                invoked_at, slot = record_invocation()
                try:
                    outcome: Outcome = Returned(method(*command.args, **command.kwargs))
                except Exception as error:
                    outcome = Raised.from_exception(error)
                record_return(thread_id, command, outcome, invoked_at, slot)
        except BaseException as error:
            with event_lock:
                worker_errors.append(error)

    def stress_worker(thread_id: int, commands: tuple[Command, ...]) -> None:
        target_code: CodeType | None = None
        line_gate: threading.Barrier | None = None
        synchronized_lines = 0
        yield_opcodes = False
        yielded_opcodes = 0
        line_timeout = _STRESS_SYNC_TIMEOUT

        def stress_trace(frame: FrameType, event: str, argument: object) -> Any:
            nonlocal synchronized_lines, yielded_opcodes
            if frame.f_code is not target_code:
                return None
            if event == "call":
                frame.f_trace_opcodes = yield_opcodes
            elif (
                event == "line"
                and synchronized_lines < _STRESS_SYNC_LINES
                and line_gate is not None
                and not line_gate.broken
            ):
                try:  # noqa: SIM105 - this is a tracing hot path
                    line_gate.wait(timeout=line_timeout)
                except threading.BrokenBarrierError:
                    pass
                synchronized_lines += 1
            elif event == "opcode" and yielded_opcodes < _STRESS_YIELD_OPCODES:
                yielded_opcodes += 1
                time.sleep(0)
            return stress_trace

        previous_trace = sys.gettrace()
        sys.settrace(stress_trace)
        try:
            start_gate.wait()
            for round_index, command in enumerate(commands):
                method: Callable[..., Any] = getattr(subject, command.name)
                invoked_at, slot = record_invocation()
                stress_active = round_gates[round_index].parties > 1
                if not stress_active:
                    line_gate = None
                else:
                    invocation_gate = round_gates[round_index]
                    line_gate = line_gates[round_index]
                    function = getattr(method, "__func__", method)
                    code = getattr(function, "__code__", None)
                    target_code = code if isinstance(code, CodeType) else None
                    synchronized_lines = 0
                    yielded_opcodes = 0
                    yield_opcodes = target_code is not None and _should_yield_opcodes(
                        target_code
                    )
                    line_timeout = (
                        _STRESS_SYNC_TIMEOUT
                        if deadline is None
                        else max(
                            min(deadline - time.monotonic(), _STRESS_SYNC_TIMEOUT),
                            0,
                        )
                    )
                    invocation_gate.wait()
                    if target_code is None:
                        time.sleep(0)
                try:
                    outcome: Outcome = Returned(method(*command.args, **command.kwargs))
                except Exception as error:
                    outcome = Raised.from_exception(error)
                finally:
                    target_code = None
                    line_gate = None
                    yield_opcodes = False
                record_return(thread_id, command, outcome, invoked_at, slot)
        except BaseException as error:
            for gate in (*round_gates, *line_gates):
                gate.abort()
            with event_lock:
                worker_errors.append(error)
        finally:
            sys.settrace(previous_trace)

    worker = stress_worker if stress_enabled else native_worker
    workers = [
        threading.Thread(
            target=worker,
            args=(thread_id, commands),
            name=f"linpoint-{thread_id}",
            daemon=True,
        )
        for thread_id, commands in enumerate(scenario.threads)
    ]
    started: list[threading.Thread] = []
    try:
        for thread in workers:
            thread.start()
            started.append(thread)
    except BaseException:
        start_gate.abort()
        for thread in started:
            thread.join()
        raise

    start_timed_out = False
    try:
        remaining = None if deadline is None else max(deadline - time.monotonic(), 0)
        start_gate.wait(timeout=remaining)
    except threading.BrokenBarrierError:
        start_timed_out = True

    for thread in workers:
        remaining = None if deadline is None else max(deadline - time.monotonic(), 0)
        thread.join(remaining)

    active_threads = tuple(
        thread_id for thread_id, thread in enumerate(workers) if thread.is_alive()
    )
    if start_timed_out or active_threads:
        for gate in (*round_gates, *line_gates):
            gate.abort()
        with event_lock:
            partial_history = History(tuple(call for call in calls if call is not None))
        raise RunTimedOut(partial_history, active_threads)

    if worker_errors:
        raise worker_errors[0]
    return History(tuple(call for call in calls if call is not None))
