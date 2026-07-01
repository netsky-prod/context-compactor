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
