from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from ._history import Call, Command, History, Outcome, Raised, Returned


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


def run(implementation: Callable[[], Any], scenario: Scenario) -> History:
    """Execute a scenario against one shared implementation instance."""

    subject = implementation()
    start_gate = threading.Barrier(len(scenario.threads) + 1)
    event_lock = threading.Lock()
    calls: list[Call] = []
    worker_errors: list[BaseException] = []
    next_event = 0

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
        try:
            start_gate.wait()
            for command in commands:
                invoked_at = record_invocation()
                method: Callable[..., Any] = getattr(subject, command.name)
                try:
                    outcome: Outcome = Returned(method(*command.args, **command.kwargs))
                except Exception as error:
                    outcome = Raised.from_exception(error)
                record_return(thread_id, command, outcome, invoked_at)
        except BaseException as error:
            with event_lock:
                worker_errors.append(error)

    workers = [
        threading.Thread(
            target=worker,
            args=(thread_id, commands),
            name=f"linpoint-{thread_id}",
        )
        for thread_id, commands in enumerate(scenario.threads)
    ]
    for thread in workers:
        thread.start()
    start_gate.wait()
    for thread in workers:
        thread.join()

    if worker_errors:
        raise worker_errors[0]
    return History(tuple(sorted(calls, key=lambda call: call.invoked_at)))
