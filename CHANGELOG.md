# Changelog

All notable changes to `argon-agents` are recorded here. Versions follow
[Semantic Versioning](https://semver.org/). Releases before 0.3.0 are
described on [GitHub Releases](https://github.com/argon-lab/argon-agents/releases).

## [Unreleased]

### Changed

- Documentation: write-back to an imported source (including MongoDB Atlas)
  is a CLI step the SDK does not wrap; `credential=True` is refused on an
  unauthenticated deployment and when the engine runs on Atlas; indexes are
  not versioned and Atlas Search indexes are not built in sandboxes; the
  Mem0 example reviews a plan before applying it. No hosted service is
  referenced any more.
- CI tests against Argon v2.13.0.

## [0.3.0] - 2026-11-21

### Added

- `ArgonClient.create_sandbox(..., credential=True)`, and the `credential`
  keyword on `ArgonCheckpointSaver.from_sandbox()` and `.fork()`. With Argon
  2.10.0 or later, on a deployment that enforces authentication, the
  sandbox's connection string carries a MongoDB user that can read and write
  only that sandbox's database; Argon returns it once and revokes it when the
  sandbox is discarded or swept.
- `Sandbox.indexes` (secondary indexes the checkout built) and
  `Sandbox.index_notes` (TTL indexes built without expiry, and indexes the
  data violates), from Argon 2.11.0. Older engines report `0` and `[]`.

### Unchanged

- `sandboxed_mem0_config` keeps the engine's credentials because it runs
  `collMod`.

### Compatibility

- Minimum engine: Argon 2.1.1. Recommended and tested: Argon 2.12.0.
  Python 3.10 or later.

Install: `python3 -m pip install 'argon-agents==0.3.0'` (add `[langgraph]`
for the LangGraph checkpointer).
