#!/usr/bin/env bash
set -euo pipefail

PACKAGE_NAME="${LEADS_PACKAGE_NAME:-leads-cli}"
SKIP_INIT="${LEADS_SKIP_INIT:-0}"
LEADS_PYTHON_VERSION="${LEADS_PYTHON_VERSION:-3.13}"

command_exists() {
  command -v "$1" >/dev/null 2>&1
}

find_python() {
  if command_exists python3; then
    command -v python3
    return
  fi
  if command_exists python; then
    command -v python
    return
  fi
  printf 'Python 3 is required to install %s.\n' "$PACKAGE_NAME" >&2
  exit 1
}

PYTHON_BIN="$(find_python)"

run_pipx() {
  if command_exists pipx; then
    pipx "$@"
  else
    "$PYTHON_BIN" -m pipx "$@"
  fi
}

find_leads() {
  if command_exists leads; then
    command -v leads
    return
  fi
  if [ -x "$HOME/.local/bin/leads" ]; then
    printf '%s\n' "$HOME/.local/bin/leads"
    return
  fi
  return 1
}

printf 'Installing %s with pipx using Python %s...\n' "$PACKAGE_NAME" "$LEADS_PYTHON_VERSION"
if ! command_exists pipx; then
  "$PYTHON_BIN" -m pip install --user pipx
  "$PYTHON_BIN" -m pipx ensurepath || true
fi

PIPX_PYTHON_ARGS=(--python "$LEADS_PYTHON_VERSION")
if run_pipx install --help 2>/dev/null | grep -q -- '--fetch-python'; then
  PIPX_PYTHON_ARGS+=(--fetch-python missing)
fi

if run_pipx list --short 2>/dev/null | grep -qx "$PACKAGE_NAME"; then
  run_pipx reinstall "${PIPX_PYTHON_ARGS[@]}" "$PACKAGE_NAME"
else
  run_pipx install "${PIPX_PYTHON_ARGS[@]}" "$PACKAGE_NAME"
fi

if [ "$SKIP_INIT" = "1" ]; then
  printf 'Installed %s. Run `leads init` when you are ready.\n' "$PACKAGE_NAME"
  exit 0
fi

if LEADS_BIN="$(find_leads)"; then
  "$LEADS_BIN" init
else
  printf 'Could not find `leads` on PATH yet; running the package through pipx once.\n'
  run_pipx run "${PIPX_PYTHON_ARGS[@]}" --spec "$PACKAGE_NAME" leads init
fi
