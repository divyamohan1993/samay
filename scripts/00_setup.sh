#!/usr/bin/env bash
# Idempotent, zero-intervention setup for SAMAY / pqcsched on a blank CPU box.
# CPU-only: this is pure optimization — no GPU, no CUDA, none needed.
# Safe to re-run. Creates a local venv and installs the package + its deps.
set -euo pipefail
cd "$(dirname "$0")/.."

PY="${PYTHON:-python3.12}"

if ! command -v "$PY" >/dev/null 2>&1; then
  echo "[setup] installing python3.12 + build tools"
  sudo apt-get update -qq
  sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq \
    python3.12 python3.12-venv build-essential git
fi

if [ ! -d venv ]; then
  echo "[setup] creating venv"
  "$PY" -m venv venv
fi

echo "[setup] installing pqcsched (CP-SAT primary; HiGHS/CBC fallback; Gurobi optional)"
./venv/bin/python -m pip install -U pip wheel -q
./venv/bin/python -m pip install -e . -q
./venv/bin/python -m pip freeze > requirements.lock.txt

echo "[setup] smoke test"
./venv/bin/python -c "from pqcsched import tiny_instance, solve_cpsat, RiskModel; \
i=tiny_instance(); r=solve_cpsat(i, RiskModel(), time_limit=10, workers=$(nproc)); \
print('smoke:', r.status, 'risk=', r.objective, 'in', round(r.wall_time,2),'s on', $(nproc),'workers')"

echo "[setup] done. requirements.lock.txt written."
