#!/usr/bin/env bash
# Idempotent bootstrap for the goldarb-lab development environment.
# Creates a project virtualenv and installs the package with dev + pandas extras.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="$REPO_DIR/.venv"

# The base image ships an externally-managed system Python, so use a venv.
# Some base images lack ensurepip, which only fails at creation time, so
# create the venv and install the matching python*-venv package on failure.
if ! python3 -m venv "$VENV_DIR" 2>/dev/null; then
  PY_VER="$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
  sudo apt-get update -qq
  sudo apt-get install -y "python${PY_VER}-venv"
  python3 -m venv "$VENV_DIR"
fi
"$VENV_DIR/bin/python" -m pip install --upgrade pip
"$VENV_DIR/bin/pip" install -e "$REPO_DIR[pandas,dev]"

# Auto-activate the venv for interactive shells so python/pytest resolve to it.
ACTIVATE_LINE="source \"$VENV_DIR/bin/activate\""
if ! grep -qxF "$ACTIVATE_LINE" "$HOME/.bashrc" 2>/dev/null; then
  echo "$ACTIVATE_LINE" >> "$HOME/.bashrc"
fi
