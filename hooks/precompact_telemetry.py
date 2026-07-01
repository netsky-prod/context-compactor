import json
import os
import shutil
import sys
from dataclasses import asdict
from pathlib import Path

# Allow running as a standalone hook script: ensure repo root is importable.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from compactor.config import CompactConfig
from compactor.engine import compact
from compactor.summarizer import get_summarizer
from compactor.tokens import HeuristicCounter
from compactor.transcript import load


def main(stdin_text: str, base_dir: str, now: str) -> int:
    """PreCompact hook (honest role): back up the transcript and log the token
    savings our compactor WOULD achieve. Never blocks, never raises — a telemetry
    hook must not break the session."""
    try:
        payload = json.loads(stdin_text)
        session_id = payload.get("session_id", "unknown")
        transcript_path = payload.get("transcript_path")
        trigger = payload.get("trigger", "unknown")
        base = Path(base_dir)
        (base / "backups").mkdir(parents=True, exist_ok=True)
        if transcript_path and Path(transcript_path).exists():
            shutil.copy2(transcript_path, base / "backups" / f"{session_id}-{now}.jsonl")
            messages, _ = load(transcript_path)
            cfg = CompactConfig()
            res = compact(messages, cfg, get_summarizer(cfg.summarizer_name), HeuristicCounter())
            row = {"ts": now, "session_id": session_id, "trigger": trigger,
                   "stats": asdict(res["stats"])}
            with open(base / "telemetry.jsonl", "a", encoding="utf-8") as fh:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    except Exception:
        pass  # never break the session
    return 0


if __name__ == "__main__":
    from datetime import datetime, timezone

    home = os.environ.get("HOME", ".")
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%S")
    raise SystemExit(main(sys.stdin.read(), base_dir=f"{home}/.claude/compactor", now=ts))
