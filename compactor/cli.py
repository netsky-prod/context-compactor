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
    p.add_argument("--report", action="store_true", help="print stats, write nothing")
    p.add_argument("--out", default=None, help="write compacted transcript to PATH")
    return p


def run(argv) -> int:
    args = _parser().parse_args(argv)
    cfg = build_config(args)
    messages, records = load(args.path)
    res = compact(messages, cfg, get_summarizer(cfg.summarizer_name), HeuristicCounter())
    st = res["stats"]
    print(f"tool_results: {st.tool_results_total}  kept_raw: {st.kept_raw}  summarized: {st.summarized}")
    print(f"tokens_before: {st.tokens_before}  tokens_after: {st.tokens_after}  reduction: {st.reduction_pct}%")
    # apply() reads _record_index from messages and writes into records; dump()
    # serializes records, which never carry _record_index, so it cannot leak.
    if args.out and not args.report:
        updated = apply(records, res["messages"])
        dump(updated, args.out)
    return 0
