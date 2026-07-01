from dataclasses import dataclass, fields


@dataclass(frozen=True)
class CompactConfig:
    n_keep_raw: int = 8
    min_chars_to_summarize: int = 500
    summarizer_name: str = "truncate"

    @classmethod
    def from_dict(cls, d: dict) -> "CompactConfig":
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in (d or {}).items() if k in known})
