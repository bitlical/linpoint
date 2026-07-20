import subprocess
import sys
from importlib.metadata import version

import linpoint


def test_public_version_matches_distribution_metadata() -> None:
    assert linpoint.__version__ == version("linpoint")


def test_core_import_does_not_eagerly_load_hypothesis() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; import linpoint; assert 'hypothesis' not in sys.modules",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr


def test_lazy_exports_remain_discoverable() -> None:
    assert "Spec" in dir(linpoint)
    assert "verify" in dir(linpoint)
