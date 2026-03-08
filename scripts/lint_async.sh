#!/usr/bin/env bash
# lint_async.sh — Prevent sync event-loop calls in async codebase
# Rationale: run_until_complete inside an already-running loop causes
# RuntimeError. All I/O must use 'await'. (incident 2025-02-13)

set -euo pipefail

BANNED_PATTERNS=(
  "run_until_complete"
  "loop\.run_forever"
)

EXIT=0
for pattern in "${BANNED_PATTERNS[@]}"; do
  # Search project .py files, exclude venv / .venv / node_modules
  HITS=$(grep -rn "$pattern" --include="*.py" \
    --exclude-dir=venv --exclude-dir=.venv --exclude-dir=node_modules \
    . 2>/dev/null || true)
  if [[ -n "$HITS" ]]; then
    echo "❌ Banned pattern '$pattern' found in project code:"
    echo "$HITS"
    EXIT=1
  fi
done

if [[ $EXIT -eq 0 ]]; then
  echo "✅ No banned async patterns found."
fi
exit $EXIT
