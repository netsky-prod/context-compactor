import copy
import json

_ROLE_TYPES = {"assistant", "user"}


def load(path):
    """Parse a Claude Code transcript JSONL. Returns (messages, records) where
    records is every parsed line in order, and messages are canonical
    {role, content, _record_index} dicts extracted from role-bearing lines."""
    records = []
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    messages = []
    for i, rec in enumerate(records):
        if rec.get("type") in _ROLE_TYPES:
            msg = rec.get("message")
            if isinstance(msg, dict) and "role" in msg and "content" in msg:
                messages.append(
                    {"role": msg["role"], "content": msg["content"], "_record_index": i}
                )
    return messages, records


def apply(records, messages):
    """Write each canonical message's content back into its source record.
    Returns a deep copy; the input records are untouched."""
    out = copy.deepcopy(records)
    for m in messages:
        idx = m.get("_record_index")
        if idx is not None:
            out[idx]["message"]["content"] = m["content"]
    return out


def dump(records, path):
    with open(path, "w", encoding="utf-8") as fh:
        for rec in records:
            fh.write(json.dumps(rec, ensure_ascii=False, separators=(",", ":")) + "\n")
