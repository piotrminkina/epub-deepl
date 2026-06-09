# Technology Stack — epub-translation-prepare

**Status:** Approved
**Related:** `prd.md` (requirements), `tech-spec.md` (TBD — internal architecture)

---

## 1. Overview

A solo-user Python CLI tool with strict dependency minimalism. The stack is
chosen for three properties: (a) mature XML/ZIP tooling, (b) fast iteration
loop for solo development, (c) reproducible execution environment via
devcontainer for parity between development, tests, and any future CI.

Every dependency below has been chosen because the standard library or the
single non-stdlib dependency (`lxml`) cannot replace it without losing
correctness or significantly increasing implementation effort.

---

## 2. Core Runtime Stack

### Language

- **Python ≥ 3.11**
  - Why: modern type hints (`X | Y`, `Self`, `TypeAlias`), structural pattern
    matching (clean OPF/NCX element dispatch), `tomllib` in stdlib (for any
    future config), `ExceptionGroup` for batched validation errors.
  - Why not Python 3.10: `tomllib` arrived in 3.11 and pattern-matching
    ergonomics improved.
  - Why not 3.12+ floor: 3.11 is on every current LTS distribution; raising
    the floor without reason limits portability.

### Runtime dependencies (production)

| Package | Version | Purpose | Justification |
|---|---|---|---|
| `lxml` | `>= 5.0` | XML / HTML / XHTML parsing and serialization | Cython-backed libxml2/libxslt. Only library that handles XHTML 1.1 (EPUB 2 content), HTML5, and namespaced XML uniformly with a single API. Standard library's `xml.etree` cannot serialize HTML5, mishandles namespaces, and lacks fragment-based selection. |

**Total non-stdlib runtime dependencies: 1.**

### Standard library use

| Module | Use case |
|---|---|
| `zipfile` | Read input EPUB; write output EPUB with explicit `mimetype`-first STORED layout |
| `argparse` | CLI surface (two subcommands, no nesting) |
| `pathlib` | Filesystem paths |
| `logging` | Structured stderr output |
| `sys` | Exit codes, stderr |
| `re` | Limited normalized whitespace for label comparison |
| `dataclasses` | Internal data carriers (Spine, ManifestItem, NavPoint) |
| `enum` | Exit code constants, EPUB version sentinels |
| `io` | In-memory byte buffers for ZIP manipulation |
| `typing` | Type annotations |

Explicitly **not** used: `xml.etree` (replaced by `lxml`), `subprocess` (no
external command invocation in MVP), `urllib` (no network), `os.system`
(forbidden), `requests` (no network), `httpx` (no network).

---

## 3. Development Tooling

### Build / packaging

- **`hatchling` + `hatch`** (build backend + project tool).
  - Why: PEP 517-compliant, simple `pyproject.toml`, no `setup.py`, no
    `setuptools` baggage. `hatch` provides script entry points, environment
    management, version bumping in one tool.
  - Why not `setuptools`: legacy, more boilerplate.
  - Why not `poetry`: lock file flavour is opinionated; `hatch` integrates
    cleaner with `pip install -e .`.
  - Why not `uv` as build backend: `uv` excels at fast installs; build
    backend role is still maturing as of mid-2026.

### Linting and formatting

- **`ruff`** (linter + formatter, single binary, replaces `flake8`, `isort`,
  `black`, `pyupgrade`, `pylint`, `pydocstyle`).
  - Why: 10–100× faster than the Python-based alternatives; one config
    section in `pyproject.toml`.
  - Rule set: default + `E`, `F`, `W`, `I` (import sort), `B` (bugbear),
    `UP` (pyupgrade), `SIM` (simplify), `RUF` (ruff-specific), `PL`
    (pylint subset), `TCH` (type-checking imports), `PTH` (use pathlib).
  - Formatter: `ruff format` (Black-compatible).

### Static typing

- **`mypy`** (strict mode).
  - Why: `lxml` ships type stubs, and strict typing is the cheapest
    long-term insurance against silent breakage in a tool whose contract
    is byte-level structural preservation.
  - Configuration: `strict = true`, `warn_unused_ignores = true`,
    `disallow_any_generics = true`.
- **`lxml-stubs`** (development dependency) — official lxml type stubs.

### Pre-commit (optional, not enforced in CI)

- **`pre-commit`** runs `ruff check`, `ruff format`, and `mypy` before each
  commit. Optional because solo dev; documented but not mandatory.

---

## 4. Testing Stack

### Test runner

- **`pytest` ≥ 8**
  - Why: idiomatic Python testing; powerful fixtures; matches PRD's
    requirement for parametrized tests across the 4-EPUB test corpus.

### Test plugins

| Plugin | Purpose |
|---|---|
| `pytest-cov` | Coverage measurement; target ≥ 85% statement coverage |
| `pytest-xdist` | Parallel test execution across cores (test corpus is large EPUBs; sequential is slow) |

### Fixtures and test data

- The 4 EPUBs in `/tmp/nowe/` are read-only inputs to integration tests via
  a shared fixture (`conftest.py`).
- A minimal synthetic EPUB (~5 XHTML files, NCX, OPF) generated at
  collection time for fast unit-level structural assertions, avoiding the
  cost of repeatedly parsing 50-MB books for every test.

### External validation tool (manual, not pinned as a dev dep)

- **`epubcheck`** (W3C / Daisy Consortium) — Java tool, invoked manually by
  the user via `bash` per Success Metric SM-4. Installed inside the
  devcontainer for convenience, but not invoked from the test suite (Java
  runtime requirement; integration adds drag without proportional safety
  return for an MVP).

---

## 5. Execution Environment

### Devcontainer

- **Base image:** `mcr.microsoft.com/devcontainers/base:debian-12` is
  **rejected** because it ships with a pre-configured `vscode` user at
  UID 1000. Per project direction, we use a generic distribution image:
  - **`debian:bookworm-slim`** as the base.
  - Python 3.11 installed via `apt-get install python3 python3-venv
    python3-dev` (Debian 12 / bookworm ships Python 3.11 as the system
    Python). This matches the PRD's TC-1 floor exactly; no third-party
    PPA needed.
  - Build tools (`build-essential`, `libxml2-dev`, `libxslt1-dev`,
    `zlib1g-dev`) installed for `lxml` source builds — though wheels are
    preferred at runtime.
  - Optional system tools installed in the same layer: `git`, `curl`,
    `ca-certificates`, `default-jre-headless` (for manual `epubcheck`),
    `unzip` (for `diff -r` round-trip integrity checks), `vim`, `less`.
- **User strategy:** the container runs as a non-root user created at
  container build time, with a UID chosen at runtime to match the host
  user via a small entrypoint shim — *no hardcoded UID 1000*, no
  pre-existing `vscode` user. This sidesteps the bind-mount permission
  trap that hits whenever the host UID differs from 1000.
- **Workspace:** mounted at `/workspace`.

### Python environment inside the container

- A virtual environment at `/workspace/.venv` (created on first container
  start by a post-create hook), with `pip install -e .[dev]` installing
  the project plus all dev dependencies.

---

## 6. CI / Continuous Integration

Out of MVP scope. Solo project, no automation needed beyond local
pre-commit hooks. Documented as a known future addition if the project
ever has external contributors.

If added later, GitHub Actions or GitLab CI would run the same devcontainer
image to maintain dev/CI parity, executing `ruff check`, `mypy`, and
`pytest` in that order.

---

## 7. Dependency Analysis

### Supply-chain risk

- **`lxml`** is one of the most-deployed Python C-extension packages
  (used by Beautiful Soup as an optional backend, by `requests-html`, by
  scrapy, by Plone). The maintainer (Stefan Behnel) has been active for
  20+ years. Wheel coverage is comprehensive. Risk: very low.

### Vulnerability surface

- Only `lxml` exposes parsing to potentially malicious XML. We disable
  external entity resolution (`resolve_entities=False`) and DTD loading
  (`load_dtd=False`) on all parser constructions to neutralize XXE attacks.
  This is documented as a hard rule in the tech-spec.

### Update cadence

- Solo project: manual `pip list --outdated` review monthly is sufficient.
  No automated dependency update tooling (e.g., Dependabot) in MVP.

---

## 8. Alternatives Considered and Rejected

| Choice | Considered alternative | Reason rejected |
|---|---|---|
| Python | Node.js | XML library ecosystem inferior; `fast-xml-parser` and `cheerio` cannot match `lxml`'s namespaced XML handling. |
| Python | Go | `encoding/xml` is verbose and limited; no equivalent for HTML5 + XHTML 1.1 in one library; rewriting parsers in-house too costly. |
| Python | Rust | `epub` crate exists but underdeveloped; rewriting OPF/NCX parsers from scratch would 3× the timeline. |
| `lxml` | `xml.etree` (stdlib) | Lacks HTML5 mode, fragment-based selectors (XPath), namespace round-tripping fidelity, and CDATA preservation. |
| `lxml` | `BeautifulSoup` + `html5lib` | Slow on large documents (Python-pure parser); cannot serialize back to XHTML 1.1 with declarations intact. |
| `lxml` | `defusedxml` | Wrapper for security only; sits on top of `xml.etree`, inherits its limitations. Security goals achieved via lxml parser flags instead. |
| `argparse` | `click` | Nicer UX but adds dependency; PRD constraints favor zero non-essential dependencies. |
| `argparse` | `typer` | Built on `click`; same objection plus extra abstraction layer. |
| `hatch` | `poetry` | Opinionated lock file; slightly heavier; bigger PATH footprint. |
| `hatch` | `setuptools` | Legacy; more boilerplate; not aligned with PEP 621 ergonomics. |
| `hatch` | `uv` (as build backend) | `uv` is excellent as an installer but its build backend role is still emerging. Will reconsider in 6–12 months. |
| `ruff` | `flake8` + `black` + `isort` + `pyupgrade` | 4 tools, 4 config sections, 10–100× slower. `ruff` does it all. |
| `mypy` | `pyright` | Both viable; `mypy` integrates better with pytest plugins and has stricter EPUB-relevant flag presets. Marginal call. |
| `pytest` | `unittest` | Stdlib `unittest` lacks parametrization and fixtures; pytest is the de facto standard. |
| `debian:bookworm-slim` | `python:3.12-bookworm` (official Python image) | Equivalent in outcome; Debian base gives finer control over which Python comes from apt vs. source. Marginal — `python:3.12-bookworm` is the secondary fallback. |
| `debian:bookworm-slim` | `mcr.microsoft.com/devcontainers/base:debian` | Ships pre-configured `vscode` user at UID 1000 — explicitly forbidden by project direction. |
| Custom UID user | Hardcoded UID 1000 user | Bind-mount permission errors whenever host UID ≠ 1000 (typical on rootless Podman, multi-user hosts, Linux distros with non-1000 first user). |

---

## 9. Fallback Strategies

| Risk realised | Fallback |
|---|---|
| `lxml` wheel unavailable on host | Devcontainer is the supported runtime; native install instructions documented as best-effort |
| Round-trip without translation produces structural diff | Bisect: serialize ↔ parse loop until offender identified; fall back to byte-level OPF/NCX preservation (read original bytes, swap only known fields by regex within tight namespace bounds) |
| DeepL strips `data-*` attributes (R-8 catastrophic) | Re-encode markers as HTML comments `<!-- SECTION:href -->` (less robust but DeepL preserves comments per docs); ultimate fallback: split each XHTML into its own DeepL document (defeats the quota optimisation but works) |
| EPUB ≥ DeepL HTML size limit | Documented limitation; user shifts to per-XHTML translation or `bilingual_book_maker`. Out of MVP scope to chunk. |
| `epubcheck` reports errors on output | Iterate restore logic with specific error code as anchor; out-of-band — does not block release |

---

## 10. Spike / Validation Notes

Before full implementation, a short technical spike will validate the two
most uncertain mechanics:

- **Spike S-1: `mimetype`-first STORED in `zipfile`.** Verify that
  `zipfile.ZipFile.writestr` with `ZipInfo(filename='mimetype',
  compress_type=ZIP_STORED)` produces a file recognised by `epubcheck` and
  by Calibre / Apple Books readers. Estimated 30 minutes.
- **Spike S-2: DeepL HTML round-trip preserves `data-*` attributes.**
  Generate a 1-page HTML with `<section data-source-href="x">` markers,
  upload to DeepL via Pro Starter web UI, download translated, verify
  every marker survived intact. This is the R-8 sanity check. Estimated
  15 minutes user time + 1–5 minutes DeepL processing.

Both spikes complete before writing more than ~50 lines of production
code. Negative results from either spike trigger a fallback per §9 or a
scope rethink before further investment.
