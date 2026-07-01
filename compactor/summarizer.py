from typing import Protocol


class Summarizer(Protocol):
    def summarize(self, text: str, meta: dict) -> str: ...


class FakeSummarizer:
    """Deterministic summarizer for tests."""

    def summarize(self, text: str, meta: dict) -> str:
        return f"SUMMARY<{len(text)}>"


class TruncationSummarizer:
    """Deterministic, no-infra fallback: keep head+tail, elide the middle."""

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
