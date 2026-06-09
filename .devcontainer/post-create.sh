#!/usr/bin/env bash
# post-create.sh — invoked once after the container is created.
#
# Responsibilities:
#   1. Create the project virtualenv at .venv inside the workspace.
#   2. If pyproject.toml already exists, install the project in editable mode
#      with the [dev] extra. Otherwise bootstrap a known-good baseline of dev
#      tools so the user can start writing pyproject.toml without re-running
#      apt or hitting cold pip caches.
#
# Idempotent: re-running it on an already-bootstrapped tree is a no-op apart
# from `pip install` short-circuiting.

set -euo pipefail

WORKSPACE="${PWD}"
VENV_DIR="${WORKSPACE}/.venv"

echo "[post-create] workspace = ${WORKSPACE}"
echo "[post-create] python    = $(python3 --version)"

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

echo "[post-create] done. Activate with: source .venv/bin/activate"
