# Context-Compactor — Design Spec

**Date:** 2026-07-01
**Author:** devharness (Claude Code)
**Status:** DRAFT — awaiting review by `main`
**Origin:** an internal research finding (③) — "keep last ~N tool-interactions raw + auto-summarize older tool outputs" (reported −63% tokens / +20 pp quality on long-horizon; verified on Sonnet 4.5).

---

## 1. Problem & goal

Long-horizon agent sessions accumulate large, stale tool outputs (file reads, command dumps, search results). These dominate the context window yet are rarely needed verbatim after a few turns. The research finding: **keep the last N tool interactions raw, and replace the *content* of older tool outputs with compact summaries.** Reported effect: −63% tokens, +20 pp task quality on long-horizon benchmarks.

**Goal of this deliverable:** a self-contained, test-driven implementation of that algorithm for our Claude Code harness, plus the ability to *measure* the token reduction on our own real transcripts.

**Non-goal (v1):** empirically re-deriving the −63%/+20 pp numbers (deferred to a benchmark phase, see §9).

---

## 2. Critical feasibility constraint (verified against Claude Code hook docs)

The original ask names a `PreCompact` hook as a candidate implementation. **Verification of the current hook contract shows this cannot deliver live token reduction:**

| Capability | Available? |
|---|---|
| `PreCompact` inject text / steer the built-in summarizer | ❌ No — only `decision:"block"` or allow |
| Any hook rewrite/shrink **prior** `tool_result` content in live context | ❌ No — hooks are **append-only** (`additionalContext` adds, never removes) |
| `PostToolUse` `updatedToolOutput` | Replaces output of the **current** tool call only — cannot touch history |

**Consequence:** A faithful, token-*reducing* compactor **cannot** be implemented as a Claude Code hook. The only supported interception point that can actually shrink what the model receives is an **Anthropic-API-compatible proxy** at `ANTHROPIC_BASE_URL`, which rewrites each request's `messages` array before it reaches the model.

This reshapes the deliverable (see §3). It is the single most important item for `main`'s review.

---

## 3. Architecture

A pure engine at the core; thin adapters around it. Isolation is deliberate — the engine knows nothing about transcripts, hooks, HTTP, or LLM vendors.

```
                    ┌────────────────────────────────────┐
                    │  compactor.engine  (PURE, TESTED)   │
                    │  compact(messages, cfg) -> (msgs,   │
                    │                              stats)  │
                    │  - partition: last-N raw / older    │
                    │  - replace older tool_result content│
                    │    via injected Summarizer          │
                    │  - preserve tool_use↔tool_result    │
                    │    pairing; idempotent              │
                    └───────────────┬─────────────────────┘
        ┌───────────────────────────┼───────────────────────────┐
        │                           │                           │
 ┌──────▼───────┐          ┌────────▼────────┐        ┌──────────▼─────────┐
 │ CLI / transcript│       │ PreCompact hook │        │  Proxy adapter      │
 │ adapter (v1)    │       │  (v1, telemetry)│        │  (v2, DOCUMENTED)   │
 │ JSONL -> stats  │       │ backup + would- │        │ ANTHROPIC_BASE_URL  │
 │ + compacted out │       │ be savings log  │        │ live reduction      │
 └─────────────────┘       └─────────────────┘        └────────────────────┘

 Summarizer (injected):  FakeSummarizer (tests) | TruncationSummarizer (v1 default,
                         no infra) | LocalLLMSummarizer / ClaudeSummarizer (v2 adapters)
 TokenCounter (injected): heuristic chars/4 (v1) | real tokenizer (pluggable)
```

### 3.1 Canonical data model
The engine operates on the **Anthropic `messages` array** (`[{role, content:[block,...]}, ...]`), because that is the structure both the transcript and the API request share. Adapters convert to/from this canonical form:
- **Transcript adapter:** each JSONL line of `type:"assistant"|"user"` → `message`; non-message lines (attachments, metadata) pass through untouched on write-back.
- **Proxy adapter (v2):** request body `.messages` is already canonical.

---

## 4. The algorithm (engine)

Input: canonical `messages`, config `{n_keep_raw, summarizer, token_counter, min_chars_to_summarize}`.

1. **Enumerate tool_result blocks** in chronological order across all messages. A `tool_result` block (a content block with `type:"tool_result"`, carrying `tool_use_id`) is the unit of "tool interaction output".
2. **Partition:** the last `n_keep_raw` tool_result blocks are **kept raw**. All earlier ones are **summarization candidates**.
3. **Summarize candidates:** for each candidate whose serialized content exceeds `min_chars_to_summarize`, replace its `content` with a summary produced by the injected `Summarizer`, wrapped in a marker so it is (a) recognizable and (b) skipped on re-runs:
   ```
   [compacted:v1 orig_tokens=<n>] <summary text>
   ```
   The block keeps the **same `tool_use_id`** and `type:"tool_result"` — pairing is never broken.
4. **Never touch:** assistant `text`, `thinking`, and `tool_use` blocks; user text; system prompt; any message that is not a `tool_result`. Only bulky older tool *outputs* shrink.
5. **Return** `(new_messages, stats)` where stats = `{tool_results_total, kept_raw, summarized, tokens_before, tokens_after, reduction_pct}`.

### 4.1 Invariants (asserted in tests)
- **Pairing integrity:** every `tool_use.id` still has exactly one matching `tool_result.tool_use_id`, and vice-versa. (Anthropic API rejects orphans.)
- **Idempotency:** `compact(compact(m)) == compact(m)` — already-`[compacted:v1 …]` blocks are treated as raw and never re-summarized.
- **Order preservation:** message and block order is unchanged.
- **No-op below threshold:** if total tool_result count ≤ `n_keep_raw`, output == input (deep-equal).
- **Non-tool_result content is byte-identical** to input.

### 4.2 Edge cases handled
- `tool_result.content` as **string** vs **array of blocks** (text/image). Text is summarized; image blocks are preserved as-is (not summarizable) but counted toward "kept" — pairing preserved.
- Parallel tool calls (multiple `tool_use` in one assistant turn → multiple `tool_result` in the next user turn): each result counts individually toward N.
- `is_error:true` tool_results: summarized like any other when older (errors are usually short; often below threshold anyway).
- Summarizer failure/timeout: fall back to `TruncationSummarizer` (deterministic head+tail elision) so compaction never hard-fails.

---

## 5. Components & interfaces

### 5.1 `compactor/engine.py` (pure)
```python
def compact(messages: list[dict], config: CompactConfig) -> CompactResult
# CompactResult = { "messages": list[dict], "stats": Stats }
```
No I/O, no network, no clock, no randomness. Deterministic given a deterministic summarizer.

### 5.2 `compactor/summarizer.py`
```python
class Summarizer(Protocol):
    def summarize(self, text: str, meta: dict) -> str: ...

class TruncationSummarizer:     # v1 default, no infra
class FakeSummarizer:           # tests: e.g. returns f"SUMMARY<{len(text)}>"
# v2 adapters (interface only in v1): LocalLLMSummarizer, ClaudeSummarizer
```

### 5.3 `compactor/tokens.py`
```python
class TokenCounter(Protocol):
    def count(self, content) -> int: ...
class HeuristicCounter:  # len(serialized)/4, deterministic, no deps
```

### 5.4 `compactor/transcript.py` (adapter)
`load(path) -> (messages, envelope)` / `dump(messages, envelope, path)` — round-trips JSONL, preserving non-message lines and per-message envelope fields.

### 5.5 `compactor/cli.py`
```
python -m compactor path/to/session.jsonl [--n 8] [--summarizer truncate] \
       [--report] [--out compacted.jsonl]
```
`--report` prints the stats table (tokens before/after, % reduction) and writes nothing — this is how we measure the −63% claim on real sessions. `--out` writes a compacted transcript.

### 5.6 `hooks/precompact_telemetry.py` + settings snippet
A `PreCompact` hook (registered under both `manual` and `auto` matchers) that, on every compaction:
1. Copies the transcript to `~/.claude/compactor/backups/<session>-<ts>.jsonl`.
2. Runs the engine in report mode and appends `{ts, session, stats}` to `~/.claude/compactor/telemetry.jsonl`.
3. Exits `0` (never blocks). This is the **honest** hook role: measurement + safety backup, not live steering.

*(Timestamps come from the hook process env / OS at run time — outside the pure engine.)*

---

## 6. Configuration
Single JSON at `~/.claude/compactor/config.json`, read by CLI and hook (engine takes a plain dataclass):
```json
{ "n_keep_raw": 8, "summarizer": "truncate", "min_chars_to_summarize": 500 }
```
Defaults chosen conservatively; `n_keep_raw=8` ≈ recent working set. Tunable without code changes.

---

## 7. Testing strategy (TDD — tests written first)

All engine tests use `FakeSummarizer` + `HeuristicCounter` → fully deterministic, no infra.

**Engine unit tests**
- no-op when `#tool_results ≤ n_keep_raw` (deep-equal in==out)
- keeps exactly the last N raw; summarizes all older
- pairing integrity after compaction (no orphan tool_use/result)
- idempotency: `compact(compact(x)) == compact(x)`
- non-tool_result blocks byte-identical
- string-content and array-content tool_results both handled
- image blocks preserved, not summarized
- `min_chars_to_summarize` respected (short outputs left raw)
- parallel tool calls counted individually
- stats math correct (`reduction_pct`, counts)
- summarizer exception → truncation fallback, no raise

**Adapter tests**
- transcript round-trip preserves non-message lines & envelope
- CLI `--report` emits stats and writes nothing; `--out` writes valid JSONL

**Hook test**
- given a fixture transcript, telemetry hook writes a backup + one telemetry line, exit 0, never blocks

Run: `pytest -q`. Target: fast (<2 s), no network.

---

## 8. Repo layout
```
context-compactor/
  compactor/
    __init__.py  engine.py  summarizer.py  tokens.py
    transcript.py  cli.py  config.py
  hooks/
    precompact_telemetry.py  settings.snippet.json
  tests/
    test_engine.py  test_summarizer.py  test_transcript.py
    test_cli.py  test_hook.py  fixtures/*.jsonl
  docs/superpowers/specs/2026-07-01-context-compactor-design.md
  README.md  pyproject.toml
```
Python 3.12, stdlib-only for v1 (pytest as sole dev dep). No runtime third-party deps.

---

## 9. Phasing

**v1 (this deliverable):** pure engine + Truncation/Fake summarizers + heuristic counter + transcript adapter + CLI (incl. `--report` measurement) + PreCompact telemetry/backup hook + full test suite.

**v2 (documented, out of scope here, needs `main` sign-off):**
- **Live proxy** at `ANTHROPIC_BASE_URL` applying the engine per request — the *only* way to realize live token reduction in the CLI. Reuses the engine unchanged.
- **Real summarizer adapters:** `LocalLLMSummarizer` (self-hosted GPU endpoint, configured via env), `ClaudeSummarizer` (small Claude model).
- **Benchmark harness:** replay long-horizon sessions through the engine, measure token reduction + a task-quality proxy to test the −63%/+20 pp claim on Sonnet 4.5.

---

## 10. Risks & open questions for `main`
1. **Live reduction requires a proxy, not a hook** (§2). v1 delivers the faithful algorithm + measurement + telemetry, but *actual live savings* land in v2 (proxy). **Q: pull the proxy into v1, or keep v1 = engine+measurement and greenlight the proxy as fast-follow?** (Recommendation: keep v1 tight; proxy as v2 once the engine is proven on our telemetry.)
2. **Default `n_keep_raw` (8) and `min_chars_to_summarize` (500)** — reasonable starting points; will tune against telemetry.
3. **Summary marker format** `[compacted:v1 …]` — fine for our harness? (Enables idempotency + auditability.)
4. **Scope of "tool output":** v1 summarizes `tool_result` content only, never assistant reasoning or tool_use args. Confirm that matches the finding's intent.
```
