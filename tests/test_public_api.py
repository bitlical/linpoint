from importlib.metadata import version

import linpoint


def test_public_version_matches_distribution_metadata() -> None:
    assert linpoint.__version__ == version("linpoint")
