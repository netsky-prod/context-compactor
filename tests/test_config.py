from compactor.config import CompactConfig


def test_defaults():
    c = CompactConfig()
    assert (c.n_keep_raw, c.min_chars_to_summarize, c.summarizer_name) == (8, 500, "truncate")


def test_from_dict_partial_and_unknown():
    c = CompactConfig.from_dict({"n_keep_raw": 3, "bogus": 1})
    assert c.n_keep_raw == 3
    assert c.min_chars_to_summarize == 500  # default preserved
