# Measurement — context-compactor v1 on real sessions

Config: `truncate` summarizer, `n_keep_raw=8`, `min_chars_to_summarize=500`.
Token estimate: heuristic `ceil(chars/4)`. Reproduce: `./scripts/measure_real_sessions.sh 8`.
Sessions below are real agent transcripts, anonymized as `session-N`.

## Two denominators (state which you mean)

**A. Tool-output content only** — reduction *within* the `tool_result` content the engine touches.
This is what the CLI `--report` prints. It matches the research mechanism.

| Session (lines) | tool_results | summarized | tokens_before | tokens_after | reduction |
|---|---:|---:|---:|---:|---:|
| session-1 (3013) | 433 | 92 | 59013 | 19080 | 67.67% |
| session-2 (1718) | 316 | 86 | 66893 | 21016 | 68.58% |
| session-3 (539) | 109 | 39 | 21079 | 9216 | 56.28% |
| session-4 (348) | 72 | 33 | 24424 | 7367 | 69.84% |
| session-5 (151) | 27 | 15 | 14104 | 3984 | 71.75% |
| session-6 (276) | 54 | 11 | 7052 | 4652 | 34.03% |
| session-7 (153) | 34 | 5 | 4096 | 1544 | 62.30% |
| session-8 (289) | 71 | 6 | 3994 | 2800 | 29.89% |
| (small sessions <20 lines) | — | 0 | — | — | 0.00% (no-op) |
| **AGGREGATE** | | | **200885** | **69889** | **65.21%** |

**B. Whole live context** — all `user`/`assistant` message content actually sent to the model
(text + thinking + tool_use + tool_result). This is the real live-token impact.

| Session | ctx_before | ctx_after | reduction |
|---|---:|---:|---:|
| session-1 | 633778 | 592907 | 6.4% |
| session-2 | 382436 | 334978 | 12.4% |
| session-3 | 130115 | 117486 | 9.7% |
| session-4 (tool-heavy) | 84134 | 66568 | 20.9% |
| session-5 (tool-heavy) | 27618 | 17208 | 37.7% |
| session-6 | 46618 | 44130 | 5.3% |
| session-7 | 20351 | 17699 | 13.0% |
| **AGGREGATE** | **1393086** | **1257754** | **9.71%** |

## Interpretation
- The −63% headline **replicates within tool outputs** (65.2%), confirming the mechanism works.
- **On whole live context it is ~9.7% aggregate** in the real mix: older tool outputs are only
  ~10% of context here — most `tool_result`s are short, and the bulk of context is assistant
  reasoning + `tool_use` args (e.g. file-write payloads), which the finding deliberately does not touch.
- **Workload-dependent:** tool-output-heavy sessions benefit far more (session-4 20.9%,
  session-5 37.7%). File-read / search-dump-heavy agents are the sweet spot.

## v2 go/no-go input
Average ~10% live savings across a mixed fleet is modest for taking on a critical
`ANTHROPIC_BASE_URL` proxy dependency; but 20–38% on tool-heavy workflows may justify a
**targeted** proxy. Sensitivity levers not yet swept: lower `min_chars`, higher `n_keep_raw`,
a real (LLM) summarizer.

## Decision & key conclusion
- **v1 accepted** and kept as a measurement tool / optional compactor (CLI `--report` + telemetry hook).
- **v2 proxy — NOT built**, neither fleet-wide (~10% doesn't justify a critical `ANTHROPIC_BASE_URL`
  dependency on every agent) nor targeted (20–38% on a couple of agents isn't worth the extra moving
  parts given current context headroom). Retained as knowledge.
- **KEY CONCLUSION — where context actually goes:** the real context bottleneck in this workload is
  **reasoning + `tool_use` arguments (file-write/edit payloads), ~90%**, *not* `tool_result` dumps (~10%).
  The finding optimizes the wrong slice for this workload. **The large win would be compacting
  file-write/edit payload args** — a different, riskier transform (needs its own risk assessment; not now).
