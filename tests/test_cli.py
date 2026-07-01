import json

from compactor.cli import run


def _write_convo(p, n=10, size=1000):
    lines = []
    for i in range(n):
        lines.append(json.dumps({"type": "assistant", "message": {"role": "assistant",
            "content": [{"type": "tool_use", "id": f"t{i}", "name": "Read", "input": {}}]}}))
        lines.append(json.dumps({"type": "user", "message": {"role": "user",
            "content": [{"type": "tool_result", "tool_use_id": f"t{i}", "content": "X" * size}]}}))
    p.write_text("\n".join(lines) + "\n")


def test_report_mode_prints_reduction_and_writes_nothing(tmp_path, capsys):
    src = tmp_path / "s.jsonl"
    _write_convo(src)
    rc = run([str(src), "--n", "3", "--min-chars", "10", "--summarizer", "fake", "--report"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "reduction:" in out
    assert not (tmp_path / "out.jsonl").exists()


def test_out_mode_writes_valid_compacted_jsonl(tmp_path):
    src = tmp_path / "s.jsonl"
    _write_convo(src)
    dst = tmp_path / "out.jsonl"
    rc = run([str(src), "--n", "3", "--min-chars", "10", "--summarizer", "fake", "--out", str(dst)])
    assert rc == 0
    recs = [json.loads(l) for l in dst.read_text().splitlines()]
    assert len(recs) == 20
    assert "_record_index" not in dst.read_text()  # helper key never leaks
