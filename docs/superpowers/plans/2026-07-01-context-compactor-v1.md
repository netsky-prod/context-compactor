# Context-Compactor v1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a pure, tested engine that keeps the last N tool-result outputs raw and summarizes older ones, plus a CLI to measure token reduction on our real Claude Code sessions and an honest PreCompact hook (backup + telemetry).

**Architecture:** A dependency-free core `compact(messages, config)` operating on the canonical Anthropic `messages[]` array, with an injected `Summarizer` and `TokenCounter`. Thin adapters wrap it: a transcript loader/dumper (JSONL round-trip), a CLI with a `--report` measurement mode, and a PreCompact hook that backs up the transcript and logs would-be savings.

**Tech Stack:** Python 3.12, standard library only for runtime. `pytest` is the sole dev dependency.

## Global Constraints

- Python 3.12; **runtime = stdlib only** (no third-party runtime imports). `pytest` allowed for tests only.
- All work under the repo root. **Never touch production projects or anything outside the repo.**
- Engine is **pure**: no I/O, no network, no `time`/clock, no `random`. Deterministic given a deterministic summarizer.
- Invariants enforced by tests: **tool_use↔tool_result pairing integrity**, **idempotency** (`compact(compact(x)) == compact(x)`), **no-op below threshold** (output deep-equals input).
- Scope = summarize **`tool_result` content only**; never alter assistant `text`/`thinking`/`tool_use` blocks, user text, or system prompt.
- Summary marker format: `[compacted:v1 orig_tokens=<n>] <summary>`.
- Defaults: `n_keep_raw=8`, `min_chars_to_summarize=500`.
- Out of scope (v2): live proxy, real (self-hosted/Claude) summarizers, empirical −63%/+20pp benchmark.

---

### Task 1: Project scaffold & packaging

**Files:**
- Create: `pyproject.toml`, `compactor/__init__.py`, `tests/__init__.py`
- Create: `compactor/config.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Produces: `CompactConfig` dataclass with fields `n_keep_raw:int=8`, `min_chars_to_summarize:int=500`, `summarizer_name:str="truncate"`; classmethod `from_dict(d:dict)->CompactConfig` (ignores unknown keys, applies defaults for missing).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_config.py
from compactor.config import CompactConfig

def test_defaults():
    c = CompactConfig()
    assert (c.n_keep_raw, c.min_chars_to_summarize, c.summarizer_name) == (8, 500, "truncate")

def test_from_dict_partial_and_unknown():
    c = CompactConfig.from_dict({"n_keep_raw": 3, "bogus": 1})
    assert c.n_keep_raw == 3
    assert c.min_chars_to_summarize == 500  # default preserved
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ~/lab && python -m pytest tests/test_config.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'compactor.config'`

- [ ] **Step 3: Write minimal implementation**

```python
# pyproject.toml
[project]
name = "compactor"
version = "0.1.0"
requires-python = ">=3.12"
[tool.pytest.ini_options]
testpaths = ["tests"]
```

```python
# compactor/__init__.py
# (empty)
```

```python
# tests/__init__.py
# (empty)
```

```python
# compactor/config.py
from dataclasses import dataclass, fields

@dataclass(frozen=True)
class CompactConfig:
    n_keep_raw: int = 8
    min_chars_to_summarize: int = 500
    summarizer_name: str = "truncate"

    @classmethod
    def from_dict(cls, d: dict) -> "CompactConfig":
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in (d or {}).items() if k in known})
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ~/lab && python -m pytest tests/test_config.py -q`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
cd ~/lab && git add pyproject.toml compactor/ tests/ && git commit -m "feat: scaffold compactor package + CompactConfig"
```

---

### Task 2: TokenCounter

**Files:**
- Create: `compactor/tokens.py`
- Test: `tests/test_tokens.py`

**Interfaces:**
- Produces: `HeuristicCounter` with method `count(content)->int`. `content` is either a `str` or a list of content blocks (dicts). Counts `ceil(len(serialized)/4)` where `serialized` is the string itself, or `json.dumps` of a non-string (compact separators, `sort_keys=True` for determinism).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_tokens.py
from compactor.tokens import HeuristicCounter

def test_counts_string_by_quarter_chars():
    assert HeuristicCounter().count("a" * 40) == 10

def test_counts_structured_content_deterministically():
    c = HeuristicCounter()
    blocks = [{"type": "text", "text": "hello"}]
    assert c.count(blocks) == c.count(blocks)  # stable
    assert c.count(blocks) > 0

def test_rounds_up():
    assert HeuristicCounter().count("abc") == 1  # ceil(3/4)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ~/lab && python -m pytest tests/test_tokens.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'compactor.tokens'`

- [ ] **Step 3: Write minimal implementation**

```python
# compactor/tokens.py
import json
import math

class HeuristicCounter:
    def count(self, content) -> int:
        s = content if isinstance(content, str) else json.dumps(
            content, separators=(",", ":"), sort_keys=True, ensure_ascii=False
        )
        return math.ceil(len(s) / 4)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ~/lab && python -m pytest tests/test_tokens.py -q`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
cd ~/lab && git add compactor/tokens.py tests/test_tokens.py && git commit -m "feat: HeuristicCounter token estimator"
```

---

### Task 3: Summarizers (Fake + Truncation)

**Files:**
- Create: `compactor/summarizer.py`
- Test: `tests/test_summarizer.py`

**Interfaces:**
- Produces:
  - `Summarizer` Protocol: `summarize(text:str, meta:dict)->str`.
  - `FakeSummarizer`: returns `f"SUMMARY<{len(text)}>"` (deterministic; for tests).
  - `TruncationSummarizer(head:int=200, tail:int=200)`: if `len(text)<=head+tail` returns `text`; else returns `text[:head] + f"\n…[{len(text)-head-tail} chars elided]…\n" + text[-tail:]`.
  - `get_summarizer(name:str)->Summarizer`: `"truncate"`→`TruncationSummarizer()`, `"fake"`→`FakeSummarizer()`; unknown raises `ValueError`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_summarizer.py
import pytest
from compactor.summarizer import FakeSummarizer, TruncationSummarizer, get_summarizer

def test_fake_is_deterministic():
    f = FakeSummarizer()
    assert f.summarize("hello", {}) == "SUMMARY<5>"

def test_truncation_shortens_long_text_and_keeps_ends():
    s = TruncationSummarizer(head=5, tail=5)
    out = s.summarize("A" * 3 + "B" * 100 + "C" * 3, {})
    assert out.startswith("AAABB")
    assert out.endswith("BBCCC")
    assert "elided" in out
    assert len(out) < 106

def test_truncation_noop_when_short():
    s = TruncationSummarizer(head=200, tail=200)
    assert s.summarize("short", {}) == "short"

def test_get_summarizer_unknown_raises():
    with pytest.raises(ValueError):
        get_summarizer("nope")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ~/lab && python -m pytest tests/test_summarizer.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'compactor.summarizer'`

- [ ] **Step 3: Write minimal implementation**

```python
# compactor/summarizer.py
from typing import Protocol

class Summarizer(Protocol):
    def summarize(self, text: str, meta: dict) -> str: ...

class FakeSummarizer:
    def summarize(self, text: str, meta: dict) -> str:
        return f"SUMMARY<{len(text)}>"

class TruncationSummarizer:
    def __init__(self, head: int = 200, tail: int = 200):
        self.head, self.tail = head, tail

    def summarize(self, text: str, meta: dict) -> str:
        if len(text) <= self.head + self.tail:
            return text
        elided = len(text) - self.head - self.tail
        return f"{text[:self.head]}\n…[{elided} chars elided]…\n{text[-self.tail:]}"

def get_summarizer(name: str) -> Summarizer:
    if name == "truncate":
        return TruncationSummarizer()
    if name == "fake":
        return FakeSummarizer()
    raise ValueError(f"unknown summarizer: {name}")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ~/lab && python -m pytest tests/test_summarizer.py -q`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
cd ~/lab && git add compactor/summarizer.py tests/test_summarizer.py && git commit -m "feat: Fake + Truncation summarizers"
```

---

### Task 4: Engine — tool_result enumeration & partitioning helpers

**Files:**
- Create: `compactor/engine.py`
- Test: `tests/test_engine_partition.py`

**Interfaces:**
- Produces (internal, but tested):
  - `MARKER_PREFIX = "[compacted:v1"`.
  - `iter_tool_results(messages)->list[tuple[int,int,dict]]`: returns `(msg_index, block_index, block)` for every content block with `type=="tool_result"`, in document order. Only messages whose `content` is a list are scanned; string content is ignored.
  - `is_already_compacted(block)->bool`: True if the block's serialized text content starts with `MARKER_PREFIX`.
  - `block_text(block)->str`: returns the summarizable text of a tool_result — if `content` is a str, that str; if a list, the concatenation of `text` fields of `type=="text"` sub-blocks (image/other sub-blocks contribute nothing).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_engine_partition.py
from compactor.engine import iter_tool_results, is_already_compacted, block_text

def _msgs():
    return [
        {"role": "assistant", "content": [{"type": "tool_use", "id": "t1", "name": "Read", "input": {}}]},
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1", "content": "hello"}]},
        {"role": "assistant", "content": "plain string content ignored"},
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "t2",
             "content": [{"type": "text", "text": "abc"}, {"type": "image", "source": {}}]},
        ]},
    ]

def test_iter_finds_all_tool_results_in_order():
    got = iter_tool_results(_msgs())
    assert [b["tool_use_id"] for (_, _, b) in got] == ["t1", "t2"]
    assert got[0][0] == 1  # msg index of first result

def test_block_text_string_and_list():
    _, _, b1 = iter_tool_results(_msgs())[0]
    _, _, b2 = iter_tool_results(_msgs())[1]
    assert block_text(b1) == "hello"
    assert block_text(b2) == "abc"  # image contributes nothing

def test_is_already_compacted():
    assert is_already_compacted({"type": "tool_result", "tool_use_id": "x",
                                 "content": "[compacted:v1 orig_tokens=9] s"})
    assert not is_already_compacted({"type": "tool_result", "tool_use_id": "x", "content": "raw"})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ~/lab && python -m pytest tests/test_engine_partition.py -q`
Expected: FAIL — `ImportError: cannot import name 'iter_tool_results'`

- [ ] **Step 3: Write minimal implementation**

```python
# compactor/engine.py
MARKER_PREFIX = "[compacted:v1"

def block_text(block: dict) -> str:
    content = block.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            sub.get("text", "") for sub in content
            if isinstance(sub, dict) and sub.get("type") == "text"
        )
    return ""

def is_already_compacted(block: dict) -> bool:
    return block_text(block).startswith(MARKER_PREFIX)

def iter_tool_results(messages: list[dict]):
    out = []
    for mi, msg in enumerate(messages):
        content = msg.get("content")
        if not isinstance(content, list):
            continue
        for bi, block in enumerate(content):
            if isinstance(block, dict) and block.get("type") == "tool_result":
                out.append((mi, bi, block))
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ~/lab && python -m pytest tests/test_engine_partition.py -q`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
cd ~/lab && git add compactor/engine.py tests/test_engine_partition.py && git commit -m "feat: engine tool_result enumeration helpers"
```

---

### Task 5: Engine — `compact()` core + stats

**Files:**
- Modify: `compactor/engine.py`
- Test: `tests/test_engine_compact.py`

**Interfaces:**
- Consumes: `CompactConfig` (Task 1), `Summarizer` (Task 3), `TokenCounter` (Task 2), helpers (Task 4).
- Produces:
  - `Stats` dataclass: `tool_results_total:int`, `kept_raw:int`, `summarized:int`, `tokens_before:int`, `tokens_after:int`, `reduction_pct:float` (0.0 if `tokens_before==0`; rounded to 2 dp).
  - `compact(messages, config, summarizer, counter)->dict` returning `{"messages": new_messages, "stats": Stats}`. Does a deep copy; never mutates input. Keeps the last `config.n_keep_raw` tool_results raw; for older ones whose `block_text` length `>= min_chars_to_summarize` and not already compacted, replaces `content` with the string `f"[compacted:v1 orig_tokens={counter.count(orig_content)}] " + summarizer.summarize(text, meta)` (meta includes `tool_use_id`). On summarizer exception, falls back to `TruncationSummarizer().summarize(...)`. `tokens_before/after` sum `counter.count` over all tool_result contents.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_engine_compact.py
import copy
from compactor.config import CompactConfig
from compactor.engine import compact, MARKER_PREFIX
from compactor.summarizer import FakeSummarizer
from compactor.tokens import HeuristicCounter

def _pair(uid, content):
    return [
        {"role": "assistant", "content": [{"type": "tool_use", "id": uid, "name": "Read", "input": {}}]},
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": uid, "content": content}]},
    ]

def _convo(n, size=1000):
    msgs = []
    for i in range(n):
        msgs += _pair(f"t{i}", "X" * size)
    return msgs

def _run(msgs, cfg):
    return compact(msgs, cfg, FakeSummarizer(), HeuristicCounter())

def test_noop_below_threshold():
    msgs = _convo(3)
    cfg = CompactConfig(n_keep_raw=8)
    before = copy.deepcopy(msgs)
    res = _run(msgs, cfg)
    assert res["messages"] == before          # deep-equal, untouched
    assert msgs == before                      # input not mutated
    assert res["stats"].summarized == 0

def test_keeps_last_n_raw_summarizes_older():
    msgs = _convo(10)
    cfg = CompactConfig(n_keep_raw=3, min_chars_to_summarize=10)
    res = _run(msgs, cfg)
    st = res["stats"]
    assert st.tool_results_total == 10
    assert st.kept_raw == 3 and st.summarized == 7
    # last 3 still raw
    from compactor.engine import iter_tool_results, block_text
    trs = iter_tool_results(res["messages"])
    assert all(not block_text(b).startswith(MARKER_PREFIX) for _, _, b in trs[-3:])
    assert all(block_text(b).startswith(MARKER_PREFIX) for _, _, b in trs[:7])
    assert st.tokens_after < st.tokens_before
    assert st.reduction_pct > 0

def test_min_chars_leaves_short_outputs_raw():
    msgs = _convo(10, size=5)  # tiny outputs
    cfg = CompactConfig(n_keep_raw=1, min_chars_to_summarize=500)
    res = _run(msgs, cfg)
    assert res["stats"].summarized == 0  # nothing big enough

def test_pairing_integrity_preserved():
    msgs = _convo(10)
    cfg = CompactConfig(n_keep_raw=2, min_chars_to_summarize=10)
    res = _run(msgs, cfg)
    uses, results = set(), set()
    for m in res["messages"]:
        if isinstance(m.get("content"), list):
            for b in m["content"]:
                if b.get("type") == "tool_use": uses.add(b["id"])
                if b.get("type") == "tool_result": results.add(b["tool_use_id"])
    assert uses == results  # no orphans either direction

def test_idempotent():
    msgs = _convo(10)
    cfg = CompactConfig(n_keep_raw=2, min_chars_to_summarize=10)
    once = _run(msgs, cfg)["messages"]
    twice = compact(once, cfg, FakeSummarizer(), HeuristicCounter())["messages"]
    assert twice == once

def test_non_tool_result_content_unchanged():
    msgs = _convo(10)
    cfg = CompactConfig(n_keep_raw=2, min_chars_to_summarize=10)
    res = _run(msgs, cfg)
    # assistant tool_use blocks identical
    for orig, new in zip(msgs, res["messages"]):
        if orig["role"] == "assistant":
            assert orig["content"] == new["content"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ~/lab && python -m pytest tests/test_engine_compact.py -q`
Expected: FAIL — `ImportError: cannot import name 'compact'`

- [ ] **Step 3: Write minimal implementation**

Append to `compactor/engine.py`:

```python
import copy
from dataclasses import dataclass
from compactor.summarizer import TruncationSummarizer

@dataclass
class Stats:
    tool_results_total: int
    kept_raw: int
    summarized: int
    tokens_before: int
    tokens_after: int
    reduction_pct: float

def _set_content(block: dict, new_content) -> None:
    block["content"] = new_content

def compact(messages, config, summarizer, counter) -> dict:
    msgs = copy.deepcopy(messages)
    trs = iter_tool_results(msgs)
    total = len(trs)
    tokens_before = sum(counter.count(b.get("content", "")) for _, _, b in trs)

    keep_from = max(0, total - config.n_keep_raw)
    older = trs[:keep_from]
    kept_raw = total - len(older)
    summarized = 0

    for _, _, block in older:
        if is_already_compacted(block):
            continue
        text = block_text(block)
        if len(text) < config.min_chars_to_summarize:
            continue
        orig_tokens = counter.count(block.get("content", ""))
        meta = {"tool_use_id": block.get("tool_use_id")}
        try:
            summary = summarizer.summarize(text, meta)
        except Exception:
            summary = TruncationSummarizer().summarize(text, meta)
        _set_content(block, f"[compacted:v1 orig_tokens={orig_tokens}] {summary}")
        summarized += 1

    tokens_after = sum(counter.count(b.get("content", "")) for _, _, b in iter_tool_results(msgs))
    reduction = 0.0 if tokens_before == 0 else round(100 * (tokens_before - tokens_after) / tokens_before, 2)
    stats = Stats(total, kept_raw, summarized, tokens_before, tokens_after, reduction)
    return {"messages": msgs, "stats": stats}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ~/lab && python -m pytest tests/test_engine_compact.py -q`
Expected: PASS (6 passed)

- [ ] **Step 5: Commit**

```bash
cd ~/lab && git add compactor/engine.py tests/test_engine_compact.py && git commit -m "feat: compact() core engine + stats + invariants"
```

---

### Task 6: Summarizer fallback on failure

**Files:**
- Test: `tests/test_engine_fallback.py`

**Interfaces:**
- Consumes: `compact` (Task 5). Verifies the try/except fallback already implemented in Task 5 — no new production code expected; if the test fails, fix `compact` accordingly.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_engine_fallback.py
from compactor.config import CompactConfig
from compactor.engine import compact, iter_tool_results, block_text, MARKER_PREFIX
from compactor.tokens import HeuristicCounter

class BoomSummarizer:
    def summarize(self, text, meta):
        raise RuntimeError("backend down")

def test_summarizer_exception_falls_back_no_raise():
    msgs = [
        {"role": "assistant", "content": [{"type": "tool_use", "id": "a", "name": "R", "input": {}}]},
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "a", "content": "Z" * 2000}]},
        {"role": "assistant", "content": [{"type": "tool_use", "id": "b", "name": "R", "input": {}}]},
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "b", "content": "keep"}]},
    ]
    cfg = CompactConfig(n_keep_raw=1, min_chars_to_summarize=10)
    res = compact(msgs, cfg, BoomSummarizer(), HeuristicCounter())  # must not raise
    trs = iter_tool_results(res["messages"])
    assert block_text(trs[0][2]).startswith(MARKER_PREFIX)  # got compacted via fallback
    assert res["stats"].summarized == 1
```

- [ ] **Step 2: Run test to verify it fails or passes**

Run: `cd ~/lab && python -m pytest tests/test_engine_fallback.py -q`
Expected: PASS (fallback implemented in Task 5). If FAIL, add the `try/except` around `summarizer.summarize` in `compact`.

- [ ] **Step 3: (only if failing) fix `compact`** — ensure the `try/except Exception` wraps `summarizer.summarize` and uses `TruncationSummarizer().summarize(text, meta)`.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ~/lab && python -m pytest tests/test_engine_fallback.py -q`
Expected: PASS (1 passed)

- [ ] **Step 5: Commit**

```bash
cd ~/lab && git add tests/test_engine_fallback.py compactor/engine.py && git commit -m "test: summarizer failure falls back to truncation"
```

---

### Task 7: Transcript adapter (JSONL round-trip)

**Files:**
- Create: `compactor/transcript.py`
- Test: `tests/test_transcript.py`, `tests/fixtures/mini.jsonl`

**Interfaces:**
- Produces:
  - `load(path)->tuple[list[dict], list[dict]]`: returns `(messages, records)` where `records` is the full ordered list of parsed JSONL objects, and `messages` is the list of **canonical** `{"role","content"}` dicts extracted from records whose `type` in `{"assistant","user"}` and that carry a `.message` object with `role` and `content`. Each canonical message carries a hidden back-reference index `"_record_index"` to its record.
  - `apply(records, messages)->list[dict]`: writes each canonical message's `content` back into `records[_record_index].message.content`, returning updated records (deep-copied; input untouched).
  - `dump(records, path)->None`: writes records as JSONL (one compact `json.dumps` per line, `ensure_ascii=False`).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_transcript.py
import json, copy
from pathlib import Path
from compactor.transcript import load, apply, dump

FIX = Path(__file__).parent / "fixtures" / "mini.jsonl"

def test_load_extracts_only_role_messages():
    msgs, records = load(FIX)
    assert [m["role"] for m in msgs] == ["user", "assistant", "user"]
    assert len(records) == 5  # includes 2 non-message metadata lines

def test_apply_writes_back_and_preserves_other_records(tmp_path):
    msgs, records = load(FIX)
    orig_records = copy.deepcopy(records)
    # mutate first message content
    msgs[0]["content"] = "CHANGED"
    updated = apply(records, msgs)
    assert records == orig_records  # input records untouched (deep copy)
    # non-message records identical
    assert updated[0] == orig_records[0]
    # round-trip file
    out = tmp_path / "out.jsonl"
    dump(updated, out)
    reloaded = [json.loads(l) for l in out.read_text().splitlines()]
    assert len(reloaded) == 5
    # the changed message persisted
    changed = [r for r in reloaded if r.get("type") == "user"][0]
    assert changed["message"]["content"] == "CHANGED"
```

- [ ] **Step 2: Create the fixture**

```
# tests/fixtures/mini.jsonl  (5 lines, exact)
{"type":"file-history-snapshot","id":"snap1"}
{"type":"user","message":{"role":"user","content":"first prompt"}}
{"type":"assistant","message":{"role":"assistant","content":[{"type":"tool_use","id":"t1","name":"Read","input":{}}]}}
{"type":"user","message":{"role":"user","content":[{"type":"tool_result","tool_use_id":"t1","content":"file body"}]}}
{"type":"ai-title","title":"x"}
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd ~/lab && python -m pytest tests/test_transcript.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'compactor.transcript'`

- [ ] **Step 4: Write minimal implementation**

```python
# compactor/transcript.py
import copy
import json
from pathlib import Path

_ROLE_TYPES = {"assistant", "user"}

def load(path):
    records = []
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    messages = []
    for i, rec in enumerate(records):
        if rec.get("type") in _ROLE_TYPES:
            msg = rec.get("message")
            if isinstance(msg, dict) and "role" in msg and "content" in msg:
                messages.append({"role": msg["role"], "content": msg["content"], "_record_index": i})
    return messages, records

def apply(records, messages):
    out = copy.deepcopy(records)
    for m in messages:
        idx = m.get("_record_index")
        if idx is not None:
            out[idx]["message"]["content"] = m["content"]
    return out

def dump(records, path):
    with open(path, "w", encoding="utf-8") as fh:
        for rec in records:
            fh.write(json.dumps(rec, ensure_ascii=False, separators=(",", ":")) + "\n")
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd ~/lab && python -m pytest tests/test_transcript.py -q`
Expected: PASS (2 passed)

- [ ] **Step 6: Commit**

```bash
cd ~/lab && git add compactor/transcript.py tests/test_transcript.py tests/fixtures/mini.jsonl && git commit -m "feat: transcript JSONL load/apply/dump round-trip"
```

---

### Task 8: CLI (`--report` and `--out`)

**Files:**
- Create: `compactor/cli.py`, `compactor/__main__.py`
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: `load/apply/dump` (Task 7), `compact` (Task 5), `CompactConfig` (Task 1), `get_summarizer` (Task 3), `HeuristicCounter` (Task 2).
- Produces:
  - `build_config(args)->CompactConfig`.
  - `run(argv:list[str])->int`: parses `path` (positional), `--n`, `--summarizer`, `--min-chars`, `--report`, `--out PATH`. In `--report` mode prints a stats block to stdout and writes nothing. With `--out` writes the compacted transcript via `apply`+`dump`. Returns exit code 0 on success. `_record_index` is stripped before `compact` is handed canonical messages? No — `compact` deep-copies and ignores unknown keys; keep it so `apply` can map back. Prints `reduction_pct` line containing the substring `"reduction:"`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_cli.py
import json
from pathlib import Path
from compactor.cli import run

def _write_convo(p, n=10, size=1000):
    lines = []
    for i in range(n):
        lines.append(json.dumps({"type":"assistant","message":{"role":"assistant",
            "content":[{"type":"tool_use","id":f"t{i}","name":"Read","input":{}}]}}))
        lines.append(json.dumps({"type":"user","message":{"role":"user",
            "content":[{"type":"tool_result","tool_use_id":f"t{i}","content":"X"*size}]}}))
    p.write_text("\n".join(lines) + "\n")

def test_report_mode_prints_reduction_and_writes_nothing(tmp_path, capsys):
    src = tmp_path / "s.jsonl"; _write_convo(src)
    rc = run([str(src), "--n", "3", "--min-chars", "10", "--summarizer", "fake", "--report"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "reduction:" in out
    assert not (tmp_path / "out.jsonl").exists()

def test_out_mode_writes_valid_compacted_jsonl(tmp_path):
    src = tmp_path / "s.jsonl"; _write_convo(src)
    dst = tmp_path / "out.jsonl"
    rc = run([str(src), "--n", "3", "--min-chars", "10", "--summarizer", "fake", "--out", str(dst)])
    assert rc == 0
    recs = [json.loads(l) for l in dst.read_text().splitlines()]
    assert len(recs) == 20
    # older tool_results compacted, no _record_index leaked into file
    assert "_record_index" not in dst.read_text()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ~/lab && python -m pytest tests/test_cli.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'compactor.cli'`

- [ ] **Step 3: Write minimal implementation**

```python
# compactor/cli.py
import argparse
from compactor.config import CompactConfig
from compactor.engine import compact
from compactor.summarizer import get_summarizer
from compactor.tokens import HeuristicCounter
from compactor.transcript import load, apply, dump

def build_config(args) -> CompactConfig:
    return CompactConfig(
        n_keep_raw=args.n,
        min_chars_to_summarize=args.min_chars,
        summarizer_name=args.summarizer,
    )

def _parser():
    p = argparse.ArgumentParser(prog="compactor")
    p.add_argument("path")
    p.add_argument("--n", type=int, default=8)
    p.add_argument("--min-chars", dest="min_chars", type=int, default=500)
    p.add_argument("--summarizer", default="truncate")
    p.add_argument("--report", action="store_true")
    p.add_argument("--out", default=None)
    return p

def run(argv) -> int:
    args = _parser().parse_args(argv)
    cfg = build_config(args)
    messages, records = load(args.path)
    res = compact(messages, cfg, get_summarizer(cfg.summarizer_name), HeuristicCounter())
    st = res["stats"]
    print(f"tool_results: {st.tool_results_total}  kept_raw: {st.kept_raw}  summarized: {st.summarized}")
    print(f"tokens_before: {st.tokens_before}  tokens_after: {st.tokens_after}  reduction: {st.reduction_pct}%")
    if args.out and not args.report:
        # strip helper key so it never lands in output
        for m in res["messages"]:
            m.pop("_record_index", None) if False else None
        updated = apply(records, res["messages"])
        dump(updated, args.out)
    return 0
```

```python
# compactor/__main__.py
import sys
from compactor.cli import run
raise SystemExit(run(sys.argv[1:]))
```

Note: `apply` reads `_record_index` from each message, then writes into `records`; `dump` serializes `records` (which never contain `_record_index`), so the helper key cannot leak. The `pop(... ) if False` line is dead — remove it and rely on `apply`/`dump` on `records`.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ~/lab && python -m pytest tests/test_cli.py -q`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
cd ~/lab && git add compactor/cli.py compactor/__main__.py tests/test_cli.py && git commit -m "feat: CLI with --report measurement and --out compaction"
```

---

### Task 9: PreCompact telemetry+backup hook

**Files:**
- Create: `hooks/precompact_telemetry.py`, `hooks/settings.snippet.json`
- Test: `tests/test_hook.py`

**Interfaces:**
- Consumes: `load` (Task 7), `compact` (Task 5), `CompactConfig`/`get_summarizer`/`HeuristicCounter`.
- Produces:
  - `main(stdin_text:str, base_dir:str, now:str)->int`: parses hook JSON (`{session_id, transcript_path, trigger, ...}`), copies `transcript_path` to `<base_dir>/backups/<session_id>-<now>.jsonl`, computes stats via engine (truncate summarizer, defaults), appends one JSON line `{ts, session_id, trigger, stats}` to `<base_dir>/telemetry.jsonl`, prints nothing to stdout, returns 0 (never blocks). `now` and `base_dir` are injected (keeps testable/pure-ish; the real entrypoint supplies them from env/clock).
  - Script entrypoint reads `sys.stdin`, uses `os.environ["HOME"]/.claude/compactor` as base_dir and an ISO timestamp for `now`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_hook.py
import json
from pathlib import Path
from hooks.precompact_telemetry import main

def _make_transcript(p):
    lines = []
    for i in range(6):
        lines.append(json.dumps({"type":"assistant","message":{"role":"assistant",
            "content":[{"type":"tool_use","id":f"t{i}","name":"Read","input":{}}]}}))
        lines.append(json.dumps({"type":"user","message":{"role":"user",
            "content":[{"type":"tool_result","tool_use_id":f"t{i}","content":"Y"*1000}]}}))
    p.write_text("\n".join(lines) + "\n")

def test_hook_backs_up_and_logs_and_exits_zero(tmp_path):
    tp = tmp_path / "session.jsonl"; _make_transcript(tp)
    base = tmp_path / "compactor"
    payload = json.dumps({"session_id":"sess1","transcript_path":str(tp),"trigger":"auto"})
    rc = main(payload, base_dir=str(base), now="2026-07-01T00-00-00")
    assert rc == 0
    backups = list((base / "backups").glob("sess1-*.jsonl"))
    assert len(backups) == 1
    tel = (base / "telemetry.jsonl").read_text().splitlines()
    assert len(tel) == 1
    row = json.loads(tel[0])
    assert row["session_id"] == "sess1" and row["trigger"] == "auto"
    assert row["stats"]["tool_results_total"] == 6

def test_hook_never_raises_on_bad_input(tmp_path):
    assert main("not json", base_dir=str(tmp_path/"c"), now="t") == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ~/lab && python -m pytest tests/test_hook.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'hooks.precompact_telemetry'`

- [ ] **Step 3: Write minimal implementation**

```python
# hooks/__init__.py  (empty — makes hooks importable in tests)
```

```python
# hooks/precompact_telemetry.py
import json
import os
import shutil
import sys
from dataclasses import asdict
from pathlib import Path

# allow running as a standalone hook script: ensure repo root on path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from compactor.config import CompactConfig
from compactor.engine import compact
from compactor.summarizer import get_summarizer
from compactor.tokens import HeuristicCounter
from compactor.transcript import load

def main(stdin_text: str, base_dir: str, now: str) -> int:
    try:
        payload = json.loads(stdin_text)
        session_id = payload.get("session_id", "unknown")
        transcript_path = payload.get("transcript_path")
        trigger = payload.get("trigger", "unknown")
        base = Path(base_dir)
        (base / "backups").mkdir(parents=True, exist_ok=True)
        if transcript_path and Path(transcript_path).exists():
            shutil.copy2(transcript_path, base / "backups" / f"{session_id}-{now}.jsonl")
            messages, _ = load(transcript_path)
            cfg = CompactConfig()
            res = compact(messages, cfg, get_summarizer(cfg.summarizer_name), HeuristicCounter())
            row = {"ts": now, "session_id": session_id, "trigger": trigger,
                   "stats": asdict(res["stats"])}
            with open(base / "telemetry.jsonl", "a", encoding="utf-8") as fh:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    except Exception:
        pass  # a telemetry hook must never break the session
    return 0

if __name__ == "__main__":
    from datetime import datetime, timezone
    home = os.environ.get("HOME", ".")
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%S")
    raise SystemExit(main(sys.stdin.read(), base_dir=f"{home}/.claude/compactor", now=ts))
```

```json
// hooks/settings.snippet.json — merge into ~/.claude/settings.json
{
  "hooks": {
    "PreCompact": [
      { "matcher": "manual", "hooks": [ { "type": "command", "command": "python3 ${CLAUDE_PROJECT_DIR}/hooks/precompact_telemetry.py", "timeout": 60 } ] },
      { "matcher": "auto",   "hooks": [ { "type": "command", "command": "python3 ${CLAUDE_PROJECT_DIR}/hooks/precompact_telemetry.py", "timeout": 60 } ] }
    ]
  }
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ~/lab && python -m pytest tests/test_hook.py -q`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
cd ~/lab && git add hooks/ tests/test_hook.py && git commit -m "feat: PreCompact backup+telemetry hook (honest role, never blocks)"
```

---

### Task 10: Full suite green + README + measurement on real sessions

**Files:**
- Create: `README.md` (usage), `scripts/measure_real_sessions.sh`
- Test: run the whole suite

**Interfaces:**
- Consumes: everything. Produces: a documented way to reproduce the measurement `main` needs for the v2 go/no-go gate.

- [ ] **Step 1: Run the full test suite**

Run: `cd ~/lab && python -m pytest -q`
Expected: PASS (all tests, ~20+). If anything fails, fix before proceeding.

- [ ] **Step 2: Write the measurement script**

```bash
# scripts/measure_real_sessions.sh
#!/usr/bin/env bash
# Runs the compactor in --report mode over recent real transcripts and prints reduction %.
set -euo pipefail
N="${1:-8}"
shopt -s nullglob
for f in "$HOME"/.claude/projects/*/*.jsonl; do
  lines=$(wc -l < "$f")
  [ "$lines" -lt 20 ] && continue   # skip tiny sessions
  echo "== $f ($lines lines) =="
  python3 -m compactor "$f" --n "$N" --min-chars 500 --summarizer truncate --report || true
done
```

- [ ] **Step 3: Make it executable and run it**

Run:
```bash
cd ~/lab && chmod +x scripts/measure_real_sessions.sh && ./scripts/measure_real_sessions.sh 8 | tee /tmp/compactor-measure.txt
```
Expected: per-session `reduction: NN.NN%` lines over our real sessions. Capture the numbers for `main`.

- [ ] **Step 4: Write README**

```markdown
# context-compactor (v1)

Keeps the last N tool-result outputs raw and summarizes older ones. Pure engine + CLI + honest PreCompact hook.

## CLI
    python3 -m compactor SESSION.jsonl --n 8 --min-chars 500 --summarizer truncate --report
    python3 -m compactor SESSION.jsonl --n 8 --out compacted.jsonl

## Measure reduction on your real sessions
    ./scripts/measure_real_sessions.sh 8

## Hook (backup + telemetry; never blocks, does NOT reduce live tokens)
Merge `hooks/settings.snippet.json` into `~/.claude/settings.json`. Logs to `~/.claude/compactor/telemetry.jsonl`, backs up to `~/.claude/compactor/backups/`.

## Scope
v1 = algorithm + measurement. Live token reduction requires a v2 proxy at ANTHROPIC_BASE_URL (see spec §9); gated on v1 measured reduction being non-marginal.

## Test
    python3 -m pytest -q
```

- [ ] **Step 5: Commit**

```bash
cd ~/lab && git add README.md scripts/ && git commit -m "docs: README + real-session measurement script; v1 complete"
```

---

## Self-Review

**Spec coverage:**
- Engine algorithm §4 → Tasks 4,5,6 ✓
- Invariants §4.1 (pairing, idempotency, no-op, order, non-tool_result identical) → Task 5 tests ✓
- Edge cases §4.2 (string vs list content, images, threshold, fallback) → Tasks 4,5,6 ✓
- Summarizer interface + Fake/Truncation §5.2 → Task 3 ✓
- TokenCounter §5.3 → Task 2 ✓
- Transcript adapter §5.4 → Task 7 ✓
- CLI + `--report` measurement §5.5 → Task 8 ✓
- PreCompact hook §5.6 → Task 9 ✓
- Config §6 → Task 1 ✓
- Testing strategy §7 → all tasks ✓
- Measurement for v2 gate (main's requirement) → Task 10 ✓
- v2 items (proxy, real summarizers, benchmark) → intentionally excluded ✓

**Placeholder scan:** No TBD/TODO; every code step shows complete code. One dead line flagged in Task 8 Step 3 with explicit instruction to remove it — acceptable (teaches the invariant).

**Type consistency:** `compact(messages, config, summarizer, counter)` signature consistent across Tasks 5,6,8,9. `Stats` fields consistent (Task 5 def ↔ Task 8/9 usage). `load()->(messages, records)` consistent Tasks 7,8,9. `get_summarizer` names (`truncate`/`fake`) consistent Tasks 3,8,9.
