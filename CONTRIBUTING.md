# Contributing to Linpoint

Linpoint welcomes focused bug fixes, tests, documentation improvements, and
well-scoped feature proposals.

## Development Setup

Install [uv](https://docs.astral.sh/uv/), clone the repository, and run:

```console
uv sync --group dev
uv run pytest
```

The supported Python floor is 3.11. Changes to concurrency behavior should also
be tested with a free-threaded interpreter:

```console
uv run --isolated --python 3.14t --no-default-groups --group test pytest
```

## Quality Checks

Run every local quality gate before opening a pull request:

```console
uv run ruff check .
uv run ruff format --check .
uv run mypy src tests
uv run pytest
uv build
```

Tests should exercise public behavior rather than private implementation
details. A checker change should include either a worked history or a property
test against an independent oracle.

## Pull Requests

Keep changes small and explain the user-visible behavior. Include tests and
documentation in the same pull request when behavior changes. Do not commit
generated environments, caches, or build artifacts.

## Releases

Maintainers update `CHANGELOG.md` and the version in `pyproject.toml`, create a
matching `vX.Y.Z` GitHub release, and let the release workflow publish the exact
artifacts to PyPI through Trusted Publishing.
