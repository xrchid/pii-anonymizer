"""Consistent pseudonymization of detected PII.

Every PII span is replaced by a typed placeholder whose number is the
span's cluster: all mentions resolved to one person get the same number in
every file ([PERSON_3], [EMAIL_3], [PHONE_3] ...). Spans marked non-PII
(company names, role mailboxes, company IBANs) are left as they are.

The output is pseudonymized, not anonymized, in the GDPR sense: the
placeholder-to-value table written next to it (the "key") allows
re-identification, so it must be stored separately and access-controlled.
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

from . import dataset
from .spans import Span


def cluster_numbers(spans: list[Span]) -> dict[str, int]:
    """Map cluster labels to placeholder numbers in order of first appearance."""
    numbers: dict[str, int] = {}
    for span in spans:
        if span.is_pii and span.entity_id not in numbers:
            numbers[span.entity_id] = len(numbers) + 1
    return numbers


def placeholder(span: Span, numbers: dict[str, int]) -> str:
    return f"[{span.type}_{numbers[span.entity_id]}]"


def anonymize_text(text: str, spans: list[Span], numbers: dict[str, int]) -> str:
    """Replace PII spans of one document, right to left so offsets stay valid."""
    result = text
    for span in sorted((s for s in spans if s.is_pii), key=lambda s: s.start, reverse=True):
        if result[span.start : span.end] != span.text:
            raise ValueError(f"span does not match document text: {span}")
        result = result[: span.start] + placeholder(span, numbers) + result[span.end :]
    return result


def pseudonym_key(spans: list[Span], numbers: dict[str, int]) -> dict[str, list[str]]:
    """{placeholder: sorted distinct original values} — the re-identification key."""
    key: dict[str, set[str]] = defaultdict(set)
    for span in spans:
        if span.is_pii:
            key[placeholder(span, numbers)].add(span.text)
    return {name: sorted(values) for name, values in sorted(key.items(), key=lambda kv: _sort_key(kv[0]))}


def _sort_key(name: str) -> tuple[int, str]:
    type_, number = name.strip("[]").rsplit("_", 1)
    return int(number), type_


def anonymize_dataset(data_dir: Path, out_dir: Path, spans: list[Span], key_path: Path | None = None) -> dict[str, int]:
    """Write pseudonymized copies of the five document kinds to `out_dir`.

    gold.jsonl and decoys.jsonl are not copied (they contain the originals).
    Returns counts: documents changed and spans replaced.
    """
    numbers = cluster_numbers(spans)
    by_doc: dict[str, list[Span]] = defaultdict(list)
    for span in spans:
        by_doc[span.doc_id].append(span)
    changed = 0

    def replace_fields(doc: dataset.Document) -> str:
        nonlocal changed
        new_text = anonymize_text(doc.text, by_doc.get(doc.doc_id, []), numbers)
        changed += new_text != doc.text
        return new_text

    outputs = dataset.transform_files(Path(data_dir), replace_fields)
    dataset.write_outputs(Path(out_dir), outputs)
    if key_path is not None:
        key_path.parent.mkdir(parents=True, exist_ok=True)
        key_path.write_text(
            json.dumps(pseudonym_key(spans, numbers), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    return {"documents_changed": changed, "spans_replaced": sum(1 for s in spans if s.is_pii)}
