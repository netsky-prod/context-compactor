import json
import math


class HeuristicCounter:
    """Estimate tokens as ceil(len(serialized) / 4). Deterministic, no deps."""

    def count(self, content) -> int:
        s = content if isinstance(content, str) else json.dumps(
            content, separators=(",", ":"), sort_keys=True, ensure_ascii=False
        )
        return math.ceil(len(s) / 4)
