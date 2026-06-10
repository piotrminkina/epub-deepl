#!/usr/bin/env bash
# post-create.sh — invoked once after the container is created.
#
# Responsibilities:
#   1. Create a Python virtualenv at .venv-${PY_MINOR} inside the
#      workspace (per-minor naming; ADR-0004). Host venvs built for a
#      different Python (e.g. Fedora's 3.14) coexist at .venv-3.14
#      without conflict.
#   2. If pyproject.toml already exists, install the project in
#      editable mode with the [dev] extra. Otherwise bootstrap a
#      known-good baseline of dev tools so the user can start writing
#      pyproject.toml without re-running apt or hitting cold pip caches.
#
# Idempotent: re-running on an already-bootstrapped tree short-circuits
# on `pip install`. A versioned venv created in a prior post-create
# run for the same Python minor is reused as-is.

set -euo pipefail

readonly WORKSPACE="${PWD}"
PY_MINOR="$(python3 -c \
  'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
readonly PY_MINOR
readonly VENV_DIR="${WORKSPACE}/.venv-${PY_MINOR}"

echo "[post-create] workspace = ${WORKSPACE}"
echo "[post-create] python    = $(python3 --version)"
echo "[post-create] venv dir  = ${VENV_DIR}"

if [[ ! -d "${VENV_DIR}" ]]; then
  echo "[post-create] creating venv at ${VENV_DIR}"
  python3 -m venv "${VENV_DIR}"
fi

# shellcheck disable=SC1091
source "${VENV_DIR}/bin/activate"

python -m pip install --upgrade pip wheel setuptools

if [[ -f "${WORKSPACE}/pyproject.toml" ]]; then
  echo "[post-create] installing project (editable + dev extras)"
  pip install -e "${WORKSPACE}[dev]"
else
  echo "[post-create] pyproject.toml not present — installing dev baseline"
  pip install \
    'lxml>=5.0,<6.0' \
    'lxml-stubs' \
    'pytest>=8' \
    'pytest-cov' \
    'pytest-xdist' \
    'ruff' \
    'mypy' \
    'hatch' \
    'hatchling'
fi

# Sanity check — lxml is the only non-stdlib runtime dep; verify it imports.
python - <<'PY'
import lxml.etree
print(f"[post-create] lxml {lxml.etree.LXML_VERSION} OK; libxml2 {lxml.etree.LIBXML_VERSION}")
PY

# epubcheck sanity check
if command -v epubcheck >/dev/null 2>&1; then
  echo "[post-create] epubcheck = $(epubcheck --version 2>&1 | head -n 1)"
fi

echo "[post-create] done. Activate with: source ${VENV_DIR}/bin/activate"
