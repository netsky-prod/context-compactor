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
