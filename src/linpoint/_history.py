from __future__ import annotations

import json
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, TypeAlias

_EMPTY_KWARGS: Mapping[str, Any] = MappingProxyType({})


def _empty_kwargs() -> Mapping[str, Any]:
    return _EMPTY_KWARGS


@dataclass(frozen=True, slots=True)
class Command:
    """An operation to invoke on a shared object."""

    name: str
    args: tuple[Any, ...] = ()
    kwargs: Mapping[str, Any] = field(default_factory=_empty_kwargs)

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("command name must not be empty")
        object.__setattr__(self, "args", tuple(self.args))
        kwargs = MappingProxyType(dict(self.kwargs)) if self.kwargs else _EMPTY_KWARGS
        object.__setattr__(self, "kwargs", kwargs)


@dataclass(frozen=True, slots=True)
class Returned:
    """A value returned by an operation."""

    value: Any


@dataclass(frozen=True, slots=True)
class Raised:
    """An exception raised by an operation, without its traceback."""

    type_name: str
    args: tuple[Any, ...] = ()

    @classmethod
    def from_exception(cls, error: Exception) -> Raised:
        error_type = type(error)
        return cls(
            f"{error_type.__module__}.{error_type.__qualname__}",
            tuple(error.args),
        )


Outcome: TypeAlias = Returned | Raised


@dataclass(frozen=True, slots=True)
class Call:
    """A completed command and its invocation-to-return interval."""

    thread_id: int
    command: Command
    outcome: Outcome
    invoked_at: int
    returned_at: int

    def __post_init__(self) -> None:
        if self.returned_at < self.invoked_at:
            raise ValueError("a call cannot return before it is invoked")


@dataclass(frozen=True, slots=True)
class History:
    """An immutable collection of completed calls."""

    calls: tuple[Call, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "calls", tuple(self.calls))

    def __iter__(self) -> Iterator[Call]:
        return iter(self.calls)

    def __len__(self) -> int:
        return len(self.calls)

    def to_json(self, *, encode: Callable[[Any], Any] | None = None) -> str:
        """Serialize a history whose values are JSON-compatible."""

        calls: list[dict[str, Any]] = []
        append_call = calls.append
        for call in self.calls:
            command = call.command
            outcome_value = call.outcome
            if encode is None:
                command_args = list(command.args)
                command_kwargs = dict(command.kwargs)
            else:
                command_args = [encode(value) for value in command.args]
                command_kwargs = {
                    name: encode(value) for name, value in command.kwargs.items()
                }

            if isinstance(outcome_value, Returned):
                outcome = {
                    "kind": "returned",
                    "value": (
                        outcome_value.value
                        if encode is None
                        else encode(outcome_value.value)
                    ),
                }
            else:
                outcome = {
                    "kind": "raised",
                    "type": outcome_value.type_name,
                    "args": (
                        list(outcome_value.args)
                        if encode is None
                        else [encode(value) for value in outcome_value.args]
                    ),
                }
            append_call(
                {
                    "thread": call.thread_id,
                    "command": {
                        "name": command.name,
                        "args": command_args,
                        "kwargs": command_kwargs,
                    },
                    "outcome": outcome,
                    "invoked_at": call.invoked_at,
                    "returned_at": call.returned_at,
                }
            )
        return json.dumps(
            {"schema": "linpoint.history", "version": 1, "calls": calls},
            sort_keys=True,
            separators=(",", ":"),
        )

    @classmethod
    def from_json(
        cls, data: str, *, decode: Callable[[Any], Any] | None = None
    ) -> History:
        """Restore a history produced by :meth:`to_json`."""

        try:
            payload = json.loads(data)
            if (
                type(payload) is not dict
                or payload.get("schema") != "linpoint.history"
                or payload.get("version") != 1
                or type(payload.get("calls")) is not list
            ):
                raise ValueError

            calls: list[Call] = []
            for item in payload["calls"]:
                if type(item) is not dict:
                    raise TypeError
                command_data = item["command"]
                outcome_data = item["outcome"]
                if type(command_data) is not dict or type(outcome_data) is not dict:
                    raise TypeError
                if (
                    type(command_data.get("name")) is not str
                    or type(command_data.get("args")) is not list
                ):
                    raise TypeError
                if type(command_data.get("kwargs")) is not dict:
                    raise TypeError

                command_args = command_data["args"]
                command_kwargs = command_data["kwargs"]
                if decode is None:
                    decoded_args = tuple(command_args)
                    decoded_kwargs = command_kwargs
                else:
                    decoded_args = tuple(decode(value) for value in command_args)
                    decoded_kwargs = {
                        name: decode(value) for name, value in command_kwargs.items()
                    }
                command = Command(
                    command_data["name"],
                    decoded_args,
                    decoded_kwargs,
                )
                if outcome_data.get("kind") == "returned" and "value" in outcome_data:
                    value = outcome_data["value"]
                    outcome: Outcome = Returned(
                        value if decode is None else decode(value)
                    )
                elif outcome_data.get("kind") == "raised":
                    if (
                        type(outcome_data.get("type")) is not str
                        or type(outcome_data.get("args")) is not list
                    ):
                        raise TypeError
                    outcome_args = outcome_data["args"]
                    outcome = Raised(
                        outcome_data["type"],
                        (
                            tuple(outcome_args)
                            if decode is None
                            else tuple(decode(value) for value in outcome_args)
                        ),
                    )
                else:
                    raise ValueError

                thread_id = item.get("thread")
                invoked_at = item.get("invoked_at")
                returned_at = item.get("returned_at")
                if (
                    type(thread_id) is not int
                    or type(invoked_at) is not int
                    or type(returned_at) is not int
                ):
                    raise TypeError
                calls.append(
                    Call(
                        thread_id,
                        command,
                        outcome,
                        invoked_at,
                        returned_at,
                    )
                )
            return cls(tuple(calls))
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError("invalid Linpoint history") from error
