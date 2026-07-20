from __future__ import annotations

import json
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, TypeAlias


@dataclass(frozen=True, slots=True)
class Command:
    """An operation to invoke on a shared object."""

    name: str
    args: tuple[Any, ...] = ()
    kwargs: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("command name must not be empty")
        object.__setattr__(self, "args", tuple(self.args))
        object.__setattr__(self, "kwargs", MappingProxyType(dict(self.kwargs)))


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

        encode_value = encode or (lambda value: value)
        calls = []
        for call in self.calls:
            if isinstance(call.outcome, Returned):
                outcome = {
                    "kind": "returned",
                    "value": encode_value(call.outcome.value),
                }
            else:
                outcome = {
                    "kind": "raised",
                    "type": call.outcome.type_name,
                    "args": [encode_value(value) for value in call.outcome.args],
                }
            calls.append(
                {
                    "thread": call.thread_id,
                    "command": {
                        "name": call.command.name,
                        "args": [encode_value(value) for value in call.command.args],
                        "kwargs": {
                            name: encode_value(value)
                            for name, value in call.command.kwargs.items()
                        },
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

        decode_value = decode or (lambda value: value)
        try:
            payload = json.loads(data)
            if (
                not isinstance(payload, dict)
                or payload.get("schema") != "linpoint.history"
                or payload.get("version") != 1
                or not isinstance(payload.get("calls"), list)
            ):
                raise ValueError

            calls: list[Call] = []
            for item in payload["calls"]:
                if not isinstance(item, dict):
                    raise TypeError
                command_data = item["command"]
                outcome_data = item["outcome"]
                if not isinstance(command_data, dict) or not isinstance(
                    outcome_data, dict
                ):
                    raise TypeError
                if not isinstance(command_data.get("name"), str) or not isinstance(
                    command_data.get("args"), list
                ):
                    raise TypeError
                if not isinstance(command_data.get("kwargs"), dict) or not all(
                    isinstance(name, str) for name in command_data["kwargs"]
                ):
                    raise TypeError

                command = Command(
                    command_data["name"],
                    tuple(decode_value(value) for value in command_data["args"]),
                    {
                        name: decode_value(value)
                        for name, value in command_data["kwargs"].items()
                    },
                )
                if outcome_data.get("kind") == "returned" and "value" in outcome_data:
                    outcome: Outcome = Returned(decode_value(outcome_data["value"]))
                elif outcome_data.get("kind") == "raised":
                    if not isinstance(outcome_data.get("type"), str) or not isinstance(
                        outcome_data.get("args"), list
                    ):
                        raise TypeError
                    outcome = Raised(
                        outcome_data["type"],
                        tuple(decode_value(value) for value in outcome_data["args"]),
                    )
                else:
                    raise ValueError

                integer_fields = (
                    item.get("thread"),
                    item.get("invoked_at"),
                    item.get("returned_at"),
                )
                if not all(
                    isinstance(value, int) and not isinstance(value, bool)
                    for value in integer_fields
                ):
                    raise TypeError
                calls.append(
                    Call(
                        item["thread"],
                        command,
                        outcome,
                        item["invoked_at"],
                        item["returned_at"],
                    )
                )
            return cls(tuple(calls))
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError("invalid Linpoint history") from error
