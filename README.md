# context-compactor (v1)

Keeps the last **N** tool-result outputs raw and summarizes older ones — from a research
finding ("keep last-N tool interactions raw + auto-summarize older tool outputs").

Pure, dependency-free engine + a CLI to **measure** the effect on real sessions + an
honest `PreCompact` hook (backup + telemetry). **Runtime is stdlib-only.**

## What it does (and does not)
- **Does:** deterministically replace the *content* of older `tool_result` blocks with a
  summary, keeping the last `n_keep_raw` raw. Preserves `tool_use`↔`tool_result` pairing,
  is idempotent, and is a no-op below threshold.
- **Does NOT** touch assistant text/thinking, `tool_use` args, user text, or system prompt.
- **Does NOT** reduce *live* tokens by itself. No Claude Code hook can rewrite prior context
  (hooks are append-only; `PreCompact` can only block/allow). Real live reduction requires a
  v2 proxy at `ANTHROPIC_BASE_URL` — see the spec, gated on measured savings.

## CLI
```
python3 -m compactor SESSION.jsonl --n 8 --min-chars 500 --summarizer truncate --report
python3 -m compactor SESSION.jsonl --n 8 --out compacted.jsonl
```
`--report` prints stats and writes nothing. `--out` writes a compacted transcript.

## Measure reduction on your real sessions
```
./scripts/measure_real_sessions.sh 8
```

### Measured on our own sessions (2026-07-01, `truncate`, n=8, min-chars=500)
Two denominators — be clear which one you mean:

| Denominator | Meaning | Result |
|---|---|---|
| **tool-output content only** | reduction *within* the tool outputs we touch | **~65%** (matches research mechanism) |
| **whole live context** | all message content actually sent to the model | **~9.7% aggregate** (range 0–38%) |

The −63% headline replicates *within tool outputs*, but in the real mix older tool outputs
are only ~10% of live context (most `tool_result`s are short; the bulk of context is
reasoning + `tool_use` args). Tool-output-heavy sessions (~21–38%) benefit most. This gap
is the input to the v2 proxy go/no-go.

## Hook (backup + telemetry; never blocks, does NOT reduce live tokens)
Merge `hooks/settings.snippet.json` into `~/.claude/settings.json`. On every compaction it
backs up the transcript to `~/.claude/compactor/backups/` and appends would-be savings to
`~/.claude/compactor/telemetry.jsonl`.

## Scope
v1 = algorithm + measurement + telemetry. v2 (needs sign-off) = live proxy + real
(self-hosted/Claude) summarizers + empirical −63%/+20pp benchmark. See `docs/superpowers/specs/`
and `docs/superpowers/plans/`.

## Test
```
python3 -m pytest -q          # 25 tests, stdlib runtime; pytest is a dev-only dep
```
