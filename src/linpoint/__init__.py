from importlib.metadata import PackageNotFoundError, version

from ._checker import CheckResult, CheckStatus, check_history
from ._generation import Operation, Spec, operation, scenarios
from ._history import Call, Command, History, Outcome, Raised, Returned
from ._minimize import minimize_history
from ._model import Model, class_model
from ._runner import Scenario, run
from ._verify import Inconclusive, NonLinearizable, verify

try:
    __version__ = version("linpoint")
except PackageNotFoundError:
    __version__ = "0.0.0+unknown"

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
    "Scenario",
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
