#!/usr/bin/env bash
# Run the full SAMAY empirical study on the box: checkpointed, resumable,
# disk-guarded. Safe to re-run — the harness skips instances already in the CSVs.
# A sidecar watches free disk and stops the study before it can threaten a
# co-tenant database (the box's shared root filesystem).
set -uo pipefail
cd "$(dirname "$0")/.."

OUT="${1:-runs}"
GRID="${2:-configs/experiment.yaml}"
FLOOR_KB=1572864   # 1.5 GB floor on the output filesystem
mkdir -p "$OUT"

echo "[study] $(date -u +%FT%TZ) starting; out=$OUT grid=$GRID"
df -h / | awk 'NR==2{print "[study] disk free="$4" used="$5}'

# --- disk-guard sidecar ---------------------------------------------------
(
  while true; do
    free=$(df --output=avail -k / | tail -1 | tr -d ' ')
    if [ "${free:-0}" -lt "$FLOOR_KB" ]; then
      echo "[guard] DISK LOW (${free} KB free) — stopping study to protect shared disk"
      pkill -f "pqcsched.cli study" 2>/dev/null
      break
    fi
    sleep 30
  done
) &
GUARD=$!
trap 'kill $GUARD 2>/dev/null || true' EXIT

# --- the study ------------------------------------------------------------
./venv/bin/python -m pqcsched.cli study --grid "$GRID" --out "$OUT" 2>&1 | tee "$OUT/study.log"
rc=${PIPESTATUS[0]}

kill $GUARD 2>/dev/null || true
echo "[study] $(date -u +%FT%TZ) finished rc=$rc"
df -h / | awk 'NR==2{print "[study] disk free="$4" used="$5}'
exit "$rc"
