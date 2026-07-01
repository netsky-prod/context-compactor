import json

from hooks.precompact_telemetry import main


def _make_transcript(p):
    lines = []
    for i in range(6):
        lines.append(json.dumps({"type": "assistant", "message": {"role": "assistant",
            "content": [{"type": "tool_use", "id": f"t{i}", "name": "Read", "input": {}}]}}))
        lines.append(json.dumps({"type": "user", "message": {"role": "user",
            "content": [{"type": "tool_result", "tool_use_id": f"t{i}", "content": "Y" * 1000}]}}))
    p.write_text("\n".join(lines) + "\n")


def test_hook_backs_up_and_logs_and_exits_zero(tmp_path):
    tp = tmp_path / "session.jsonl"
    _make_transcript(tp)
    base = tmp_path / "compactor"
    payload = json.dumps({"session_id": "sess1", "transcript_path": str(tp), "trigger": "auto"})
    rc = main(payload, base_dir=str(base), now="2026-07-01T00-00-00")
    assert rc == 0
    backups = list((base / "backups").glob("sess1-*.jsonl"))
    assert len(backups) == 1
    tel = (base / "telemetry.jsonl").read_text().splitlines()
    assert len(tel) == 1
    row = json.loads(tel[0])
    assert row["session_id"] == "sess1" and row["trigger"] == "auto"
    assert row["stats"]["tool_results_total"] == 6


def test_hook_never_raises_on_bad_input(tmp_path):
    assert main("not json", base_dir=str(tmp_path / "c"), now="t") == 0
