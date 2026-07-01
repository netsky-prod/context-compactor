import json
import copy
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
    msgs[0]["content"] = "CHANGED"
    updated = apply(records, msgs)
    assert records == orig_records  # input records untouched (deep copy)
    assert updated[0] == orig_records[0]  # non-message record identical
    out = tmp_path / "out.jsonl"
    dump(updated, out)
    reloaded = [json.loads(l) for l in out.read_text().splitlines()]
    assert len(reloaded) == 5
    changed = [r for r in reloaded if r.get("type") == "user"][0]
    assert changed["message"]["content"] == "CHANGED"
