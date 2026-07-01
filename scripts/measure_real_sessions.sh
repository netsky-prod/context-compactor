#!/usr/bin/env bash
# Run the compactor in --report mode over recent real transcripts and print reduction %.
# Usage: ./scripts/measure_real_sessions.sh [N_KEEP_RAW]
set -euo pipefail
N="${1:-8}"
REPO="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO"
shopt -s nullglob
total_before=0
total_after=0
for f in "$HOME"/.claude/projects/*/*.jsonl; do
  lines=$(wc -l < "$f")
  [ "$lines" -lt 20 ] && continue   # skip tiny sessions
  echo "== $f ($lines lines) =="
  out=$(python3 -m compactor "$f" --n "$N" --min-chars 500 --summarizer truncate --report 2>/dev/null) || { echo "  (skipped: parse error)"; continue; }
  echo "$out" | sed 's/^/  /'
  b=$(echo "$out" | sed -n 's/.*tokens_before: \([0-9]*\).*/\1/p')
  a=$(echo "$out" | sed -n 's/.*tokens_after: \([0-9]*\).*/\1/p')
  total_before=$((total_before + ${b:-0}))
  total_after=$((total_after + ${a:-0}))
done
if [ "$total_before" -gt 0 ]; then
  pct=$(awk "BEGIN{printf \"%.2f\", 100*($total_before-$total_after)/$total_before}")
  echo "== AGGREGATE =="
  echo "  tokens_before: $total_before  tokens_after: $total_after  reduction: ${pct}%"
fi
