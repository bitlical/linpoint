from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ._checker import CheckResult, CheckStatus, check_history
    from ._generation import Operation, Spec, operation, scenarios
    from ._history import Call, Command, History, Outcome, Raised, Returned
    from ._minimize import minimize_history
    from ._model import Model, class_model
    from ._runner import RunTimedOut, Scenario, Scheduling, run
    from ._verify import Inconclusive, NonLinearizable, verify

    __version__: str

_CHECKER_EXPORTS = frozenset({"CheckResult", "CheckStatus", "check_history"})
_GENERATION_EXPORTS = frozenset({"Operation", "Spec", "operation", "scenarios"})
_HISTORY_EXPORTS = frozenset(
    {"Call", "Command", "History", "Outcome", "Raised", "Returned"}
)
_MINIMIZE_EXPORTS = frozenset({"minimize_history"})
_MODEL_EXPORTS = frozenset({"Model", "class_model"})
_RUNNER_EXPORTS = frozenset({"RunTimedOut", "Scenario", "Scheduling", "run"})
_VERIFY_EXPORTS = frozenset({"Inconclusive", "NonLinearizable", "verify"})


def __getattr__(name: str) -> Any:
    if name in _CHECKER_EXPORTS:
        from . import _checker

        exports = {
            "CheckResult": _checker.CheckResult,
            "CheckStatus": _checker.CheckStatus,
            "check_history": _checker.check_history,
        }
        globals().update(exports)
        return exports[name]

    if name in _GENERATION_EXPORTS:
        from . import _generation

        exports = {
            "Operation": _generation.Operation,
            "Spec": _generation.Spec,
            "operation": _generation.operation,
            "scenarios": _generation.scenarios,
        }
        globals().update(exports)
        return exports[name]

    if name in _HISTORY_EXPORTS:
        from . import _history

        exports = {
            "Call": _history.Call,
            "Command": _history.Command,
            "History": _history.History,
            "Outcome": _history.Outcome,
            "Raised": _history.Raised,
            "Returned": _history.Returned,
        }
        globals().update(exports)
        return exports[name]

    if name in _MINIMIZE_EXPORTS:
        from . import _minimize

        globals()[name] = _minimize.minimize_history
        return _minimize.minimize_history

    if name in _MODEL_EXPORTS:
        from . import _model

        exports = {
            "Model": _model.Model,
            "class_model": _model.class_model,
        }
        globals().update(exports)
        return exports[name]

    if name in _RUNNER_EXPORTS:
        from . import _runner

        exports = {
            "RunTimedOut": _runner.RunTimedOut,
            "Scenario": _runner.Scenario,
            "Scheduling": _runner.Scheduling,
            "run": _runner.run,
        }
        globals().update(exports)
        return exports[name]

    if name in _VERIFY_EXPORTS:
        from . import _verify

        exports = {
            "Inconclusive": _verify.Inconclusive,
            "NonLinearizable": _verify.NonLinearizable,
            "verify": _verify.verify,
        }
        globals().update(exports)
        return exports[name]

    if name == "__version__":
        from importlib.metadata import PackageNotFoundError, version

        try:
            package_version = version("linpoint")
        except PackageNotFoundError:
            package_version = "0.0.0+unknown"
        globals()[name] = package_version
        return package_version

    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))


__all__ = [
    "Call",
    "CheckResult",
    "CheckStatus",
    "Command",
    "History",
    "Inconclusive",
    "Model",
    "NonLinearizable",
    "Operation",
    "Outcome",
    "Raised",
    "Returned",
    "RunTimedOut",
    "Scenario",
    "Scheduling",
    "Spec",
    "check_history",
    "class_model",
    "minimize_history",
    "operation",
    "run",
    "scenarios",
    "verify",
    "__version__",
]
