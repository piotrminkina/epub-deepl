# ADR-0004: Per-Python-Minor Virtualenv Naming

**Status:** Accepted
**Date:** 2026-06-10
**Supersedes:** part of the original `bin/` launcher contract (commit
`74efc08`), which assumed a single `.venv/` per workspace.

## Context

Python's `venv` module produces a per-interpreter virtualenv whose
`site-packages` directory is named after the interpreter's minor
version (`.venv/lib/python3.11/site-packages/`). The `.venv/bin/python`
symlink resolves to the system `python3` at invocation time. The
`pyvenv.cfg` carries a `version = X.Y.Z` line but this is metadata
only — Python does NOT enforce it against the running interpreter.

Consequence: a `.venv/` built with Python 3.11 is **invisible** to a
Python 3.13 or 3.14 interpreter even though both can read each other's
source — the per-minor `site-packages` does not exist in the layout
the other interpreter expects.

This project's typical workflow exposes the gap routinely:

- The Dev Container builds a `.venv/` with Python 3.11 (Debian 12
  system Python).
- The host might run Python 3.13 or 3.14 (Fedora 41+ system Python).
- Invoking the `bin/epub-deepl` launcher from the host failed with a
  bare `No module named epub_deepl` (the venv's `site-packages/python3.11/`
  is unreadable to Python 3.14 — sys.path stays empty relative to the
  venv).

Documented in [lessons-learned G-2](../lessons-learned.md#g-2-python-venv-is-per-minor-version).

Three design options were considered for unblocking parallel
host+container use:

- **(A) Environment-named venvs** (`.venv-host/`, `.venv-container/`)
  with a "where am I" detection in the launcher (e.g., `/.dockerenv`,
  cgroup inspection).
- **(B) Per-Python-minor venvs** (`.venv-3.11/`, `.venv-3.14/`) with
  the launcher picking the one matching the system `python3`.
- **(C) Environment variable override** (e.g. `EPUB_DEEPL_VENV=path/...`).

## Decision

**Option B.** The launcher (`bin/epub-deepl`) looks up venvs in this
order:

1. `.venv-${PY_MINOR}/` (preferred — e.g. `.venv-3.11` when running
   under Python 3.11)
2. `.venv/` (legacy fallback; used only when its `pyvenv.cfg version`
   matches the current minor)

The Dev Container's `post-create.sh` creates `.venv-${PY_MINOR}/`
(e.g. `.venv-3.11/`), so host and container venvs coexist without
conflict.

If no compatible venv exists, the launcher emits a concrete creation
recipe instead of letting Python produce a bare `No module named …`.

## Consequences

**Positive:**

- Zero environment-detection heuristics — `sys.version_info` is the
  canonical truth. Robust against rootless Podman, GitHub Codespaces,
  any future container runtime.
- Generalizes to N interpreters (host 3.14, container 3.11, CI 3.12,
  …) without code changes.
- Eliminates the host↔container "who built `.venv/` last" race.
- Soft migration: existing `.venv/` keeps working via the legacy
  fallback as long as its declared version matches the current
  interpreter.

**Negative:**

- Activation path is longer: `source .venv-3.14/bin/activate` instead
  of `source .venv/bin/activate`. Documented in `CONTRIBUTING.md`
  with a helper recipe.
- A user who maintains many parallel interpreters accumulates many
  `.venv-X.Y/` directories. The cost is disk space only; each
  directory remains self-contained.

## Alternatives rejected

| Option | Rejected because |
|---|---|
| (A) Environment-named venvs | Detection of "host" vs "container" is brittle (rootless Podman, Codespaces, devcontainers in VS Code remote, all differ). Does not generalize to multiple host Pythons. |
| (C) Env var override | Requires shell configuration per-user. Defeats "just works" UX of the launcher. |

## Validation

- `shellcheck` clean on the updated launcher and `post-create.sh`.
- Round-trip from host (Python 3.14) and container (Python 3.11)
  works against the same workspace, each using its own venv.
- Existing `.venv/` from prior commits continues to work via the
  fallback path until the user rebuilds.
