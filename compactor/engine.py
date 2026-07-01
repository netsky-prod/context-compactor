import copy
from dataclasses import dataclass

from compactor.summarizer import TruncationSummarizer

MARKER_PREFIX = "[compacted:v1"


def block_text(block: dict) -> str:
    """Summarizable text of a tool_result block: the string content, or the
    concatenation of text sub-blocks (image/other sub-blocks contribute nothing)."""
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
    """Return (msg_index, block_index, block) for every tool_result block, in order.
    Only messages whose content is a list are scanned; string content is ignored."""
    out = []
    for mi, msg in enumerate(messages):
        content = msg.get("content")
        if not isinstance(content, list):
            continue
        for bi, block in enumerate(content):
            if isinstance(block, dict) and block.get("type") == "tool_result":
                out.append((mi, bi, block))
    return out


@dataclass
class Stats:
    tool_results_total: int
    kept_raw: int
    summarized: int
    tokens_before: int
    tokens_after: int
    reduction_pct: float


def compact(messages, config, summarizer, counter) -> dict:
    """Keep the last config.n_keep_raw tool_result outputs raw; replace the content
    of older ones (above the size threshold, not already compacted) with a summary.
    Never mutates the input. Preserves tool_use<->tool_result pairing. Idempotent."""
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
        block["content"] = f"[compacted:v1 orig_tokens={orig_tokens}] {summary}"
        summarized += 1

    tokens_after = sum(counter.count(b.get("content", "")) for _, _, b in iter_tool_results(msgs))
    reduction = 0.0 if tokens_before == 0 else round(
        100 * (tokens_before - tokens_after) / tokens_before, 2
    )
    stats = Stats(total, kept_raw, summarized, tokens_before, tokens_after, reduction)
    return {"messages": msgs, "stats": stats}
