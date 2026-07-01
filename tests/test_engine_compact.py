import copy

from compactor.config import CompactConfig
from compactor.engine import compact, MARKER_PREFIX, iter_tool_results, block_text
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
                if b.get("type") == "tool_use":
                    uses.add(b["id"])
                if b.get("type") == "tool_result":
                    results.add(b["tool_use_id"])
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
    for orig, new in zip(msgs, res["messages"]):
        if orig["role"] == "assistant":
            assert orig["content"] == new["content"]
