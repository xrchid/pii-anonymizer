"""Data model shared by every stage: typed character spans and JSONL helpers."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

PII_TYPES: tuple[str, ...] = (
    "PERSON",
    "EMAIL",
    "PHONE",
    "ADDRESS",
    "DATE_OF_BIRTH",
    "IBAN",
    "IP_ADDRESS",
    "CUSTOMER_ID",
    "ORGANIZATION",
)

# Fields written to gold.jsonl, in this order (the annotation contract).
GOLD_FIELDS: tuple[str, ...] = ("doc_id", "start", "end", "text", "type", "entity_id", "is_pii")


@dataclass(frozen=True)
class Span:
    """A typed mention at [start, end) in the text of one document.

    `entity_id` is the gold entity in annotations and the predicted cluster
    label in system output. `source` names the rule that produced a
    prediction, and `value` holds a normalized form (e.g. E.164 phone).
    """

    doc_id: str
    start: int
    end: int
    text: str
    type: str
    is_pii: bool = True
    entity_id: str = ""
    source: str = ""
    value: str = ""

    @property
    def length(self) -> int:
        return self.end - self.start

    def overlaps(self, other: "Span | Decoy") -> bool:
        """True when both spans are in the same document and share a character."""
        return self.doc_id == other.doc_id and self.start < other.end and other.start < self.end

    def to_dict(self) -> dict:
        return asdict(self)

    def to_gold_dict(self) -> dict:
        data = asdict(self)
        return {key: data[key] for key in GOLD_FIELDS}

    @classmethod
    def from_dict(cls, data: dict) -> "Span":
        return cls(
            doc_id=data["doc_id"],
            start=int(data["start"]),
            end=int(data["end"]),
            text=data["text"],
            type=data["type"],
            is_pii=bool(data.get("is_pii", True)),
            entity_id=data.get("entity_id", ""),
            source=data.get("source", ""),
            value=data.get("value", ""),
        )


@dataclass(frozen=True)
class Decoy:
    """Text that looks like PII to a naive detector but is not personal data."""

    doc_id: str
    start: int
    end: int
    text: str
    kind: str

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Decoy":
        return cls(data["doc_id"], int(data["start"]), int(data["end"]), data["text"], data["kind"])


def write_jsonl(path: Path, records: Iterable[dict]) -> None:
    """Write one JSON object per line, UTF-8, keys in insertion order."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(record, ensure_ascii=False) for record in records]
    path.write_text("".join(line + "\n" for line in lines), encoding="utf-8", newline="\n")


def read_jsonl(path: Path) -> list[dict]:
    with open(path, encoding="utf-8", newline="") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def write_spans(path: Path, spans: Iterable[Span]) -> None:
    write_jsonl(path, (span.to_dict() for span in spans))


def read_spans(path: Path) -> list[Span]:
    return [Span.from_dict(record) for record in read_jsonl(path)]


def read_decoys(path: Path) -> list[Decoy]:
    return [Decoy.from_dict(record) for record in read_jsonl(path)]
