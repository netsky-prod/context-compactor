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
    assert block_text(trs[0][2]).startswith(MARKER_PREFIX)  # compacted via fallback
    assert res["stats"].summarized == 1
