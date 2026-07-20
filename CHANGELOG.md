# Changelog

All notable changes to Linpoint will be documented in this file. The project
uses [Semantic Versioning](https://semver.org/).

## Unreleased

### Added

- Linearizability checking for completed concurrent histories.
- Threaded scenario execution with ordered invocation and return capture.
- Pure transition models and cloned mutable class models.
- Hypothesis-backed operation and scenario generation.
- Counterexample minimization and JSON history replay.
- Typed public API for Python 3.11 and newer, including free-threaded CPython.
- Stress scheduling for generated operations, with native scheduling as an
  explicit opt-out.

### Changed

- Replaced recursive checking with an iterative, memoized search.
- Reduced precedence construction from quadratic to `O(n log n)` time.
- Replaced one-call-at-a-time minimization with delta debugging.
- Added bounded scenario execution and stable replay-validation errors.
- Avoided retaining identity-hashed model states in the checker memo table.
- Preserved unrelated implementation and model failures after Hypothesis finds
  an earlier linearizability violation.
- Added a forced-order checker fast path and replaced generator-based DFS frames
  with bit-mask iteration.
- Reduced allocations in history minimization, JSON decoding, command creation,
  and threaded result ordering.
- Lazy-loaded public modules so core imports do not initialize Hypothesis or
  package metadata until those APIs are accessed.
