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
