from __future__ import annotations

import math
import sys
import threading
import time
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from types import CodeType, FrameType
from typing import Any, Literal, TypeAlias

from ._history import Call, Command, History, Outcome, Raised, Returned

Scheduling: TypeAlias = Literal["native", "stress"]
_STRESS_SYNC_LINES = 64
_STRESS_SYNC_TIMEOUT = 0.001
_STRESS_YIELD_OPCODES = 64


class _TraceState(threading.local):
    target_code: CodeType | None
    line_gate: threading.Barrier | None
    synchronized_lines: int
    yield_opcodes: bool
    yielded_opcodes: int

    def __init__(self) -> None:
        self.target_code = None
        self.line_gate = None
        self.synchronized_lines = 0
        self.yield_opcodes = False
        self.yielded_opcodes = 0


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
        threads = tuple(tuple(commands) for commands in self.threads)
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
    calls: list[Call] = []
    worker_errors: list[BaseException] = []
    next_event = 0
    round_gates = tuple(
        threading.Barrier(
            sum(len(commands) > round_index for commands in scenario.threads)
        )
        for round_index in range(max(map(len, scenario.threads)))
    )
    line_gates = tuple(
        threading.Barrier(
            sum(len(commands) > round_index for commands in scenario.threads)
        )
        for round_index in range(max(map(len, scenario.threads)))
    )
    trace_state = _TraceState()

    def stress_trace(frame: FrameType, event: str, argument: object) -> Any:
        if (
            trace_state.target_code is None
            or frame.f_code is not trace_state.target_code
        ):
            return None
        if event == "call":
            frame.f_trace_opcodes = trace_state.yield_opcodes
        elif event == "line":
            gate = trace_state.line_gate
            if (
                trace_state.synchronized_lines < _STRESS_SYNC_LINES
                and gate is not None
                and not gate.broken
            ):
                remaining = (
                    _STRESS_SYNC_TIMEOUT
                    if deadline is None
                    else max(
                        min(deadline - time.monotonic(), _STRESS_SYNC_TIMEOUT),
                        0,
                    )
                )
                with suppress(threading.BrokenBarrierError):
                    gate.wait(timeout=remaining)
                trace_state.synchronized_lines += 1
        elif event == "opcode" and trace_state.yielded_opcodes < _STRESS_YIELD_OPCODES:
            trace_state.yielded_opcodes += 1
            time.sleep(0)
        return stress_trace

    def record_invocation() -> int:
        nonlocal next_event
        with event_lock:
            event = next_event
            next_event += 1
            return event

    def record_return(
        thread_id: int, command: Command, outcome: Outcome, invoked_at: int
    ) -> None:
        nonlocal next_event
        with event_lock:
            returned_at = next_event
            next_event += 1
            calls.append(Call(thread_id, command, outcome, invoked_at, returned_at))

    def worker(thread_id: int, commands: tuple[Command, ...]) -> None:
        previous_trace = sys.gettrace()
        if scheduling == "stress":
            sys.settrace(stress_trace)
        try:
            start_gate.wait()
            for round_index, command in enumerate(commands):
                method: Callable[..., Any] = getattr(subject, command.name)
                invoked_at = record_invocation()
                invocation_gate = round_gates[round_index]
                trace_state.line_gate = line_gates[round_index]
                stress_active = scheduling == "stress" and invocation_gate.parties > 1
                if not stress_active:
                    trace_state.line_gate = None
                else:
                    function = getattr(method, "__func__", method)
                    code = getattr(function, "__code__", None)
                    trace_state.target_code = (
                        code if isinstance(code, CodeType) else None
                    )
                    trace_state.synchronized_lines = 0
                    if trace_state.target_code is not None:
                        body_lines = {
                            line
                            for _, _, line in trace_state.target_code.co_lines()
                            if line is not None
                            and line != trace_state.target_code.co_firstlineno
                        }
                        trace_state.yield_opcodes = len(body_lines) <= 1
                        trace_state.yielded_opcodes = 0
                    invocation_gate.wait()
                    if trace_state.target_code is None:
                        time.sleep(0)
                try:
                    outcome: Outcome = Returned(method(*command.args, **command.kwargs))
                except Exception as error:
                    outcome = Raised.from_exception(error)
                finally:
                    trace_state.target_code = None
                    trace_state.line_gate = None
                    trace_state.yield_opcodes = False
                record_return(thread_id, command, outcome, invoked_at)
        except BaseException as error:
            for gate in (*round_gates, *line_gates):
                gate.abort()
            with event_lock:
                worker_errors.append(error)
        finally:
            if scheduling == "stress":
                sys.settrace(previous_trace)

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
            partial_history = History(
                tuple(sorted(calls, key=lambda call: call.invoked_at))
            )
        raise RunTimedOut(partial_history, active_threads)

    if worker_errors:
        raise worker_errors[0]
    return History(tuple(sorted(calls, key=lambda call: call.invoked_at)))
