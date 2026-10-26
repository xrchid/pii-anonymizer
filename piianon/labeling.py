"""Hand-labelling: export documents to plain text, import inline labels as gold.

Export writes one label file per source file (crm_export.txt, invoices.txt,
tickets.txt, chats.txt, emails/thread_XX.txt). Each document is a block:

    ### crm_export.csv:1:full_name
    Emily Carter
    ### crm_export.csv:1:email
    emily.carter@brightwell.example

The text after the header line is the exact document text, followed by one
newline that separates it from the next header. Empty fields are left out
because they cannot hold personal data. Lines before the first header are
instructions and are ignored on import.

A reviewer marks personal data inline as ``[[exact text|TYPE|ENTITY_ID]]``,
for example ``[[Emily Carter|PERSON|P1]]``, using one entity id for every
mention of the same person. Import removes the markup, checks that what is
left is exactly the original document, computes offsets and writes
gold.jsonl. Every problem is reported as ``file:line: message``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from . import dataset
from .spans import PII_TYPES, Span, write_jsonl

OPEN, CLOSE, SEPARATOR = "[[", "]]", "|"
ENTITY_ID_RE = re.compile(r"[^\s|\[\]]+")
HEADER_RE = re.compile(r"^### ([^\n]*?)[ \t\r]*$", re.MULTILINE)
MAX_REPORTED_PROBLEMS = 50


class LabelError(Exception):
    """Raised with one "file:line: message" line per problem found."""


def source_name(doc_id: str) -> str:
    """'crm_export.csv:3:notes' -> 'crm_export.csv'; 'emails/thread_01.txt' stays."""
    return doc_id if doc_id.startswith(dataset.EMAIL_DIR + "/") else doc_id.split(":", 1)[0]


def label_file_name(doc_id: str) -> str:
    """'crm_export.csv:3:notes' -> 'crm_export.txt'; e-mail files keep their name."""
    return str(Path(source_name(doc_id)).with_suffix(".txt"))


def documents_by_label_file(docs: list[dataset.Document]) -> dict[str, list[dataset.Document]]:
    """Non-empty documents grouped by the label file they are written to."""
    groups: dict[str, list[dataset.Document]] = {}
    for doc in docs:
        groups.setdefault(label_file_name(doc.doc_id), [])
        if doc.text.strip():
            groups[label_file_name(doc.doc_id)].append(doc)
    return groups


# ---------------------------------------------------------------- export


def _preamble(source_name: str) -> str:
    return (
        f"# piianon label file for {source_name}\n"
        "# Mark personal data inline as [[exact text|TYPE|ENTITY_ID]], e.g. [[Emily Carter|PERSON|P1]].\n"
        f"# TYPE is one of: {' '.join(PII_TYPES)}\n"
        "# ENTITY_ID is any word without spaces; use the same id for every mention of one person.\n"
        "# Label only personal data (a sole trader's business name is ORGANIZATION; limited companies are not labelled).\n"
        "# Do not change any other character. Lines above the first '### ' header are ignored.\n"
    )


def _check_exportable(doc: dataset.Document, known_ids: set[str]) -> None:
    if OPEN in doc.text or CLOSE in doc.text:
        raise LabelError(f"{doc.doc_id}: document contains '[[' or ']]', which the label markup reserves")
    for match in HEADER_RE.finditer(doc.text):
        if match.group(1) in known_ids:
            raise LabelError(f"{doc.doc_id}: document contains a line that looks like a block header")


def _marked_up(doc: dataset.Document, spans: list[Span]) -> str:
    """Document text with `spans` written as inline labels (used for --prefill)."""
    result = doc.text
    for span in sorted(spans, key=lambda s: s.start, reverse=True):
        label = f"{OPEN}{span.text}{SEPARATOR}{span.type}{SEPARATOR}{span.entity_id or 'UNKNOWN'}{CLOSE}"
        result = result[: span.start] + label + result[span.end :]
    return result


def export_labeling(data_dir: Path, out_dir: Path, prefill: list[Span] | None = None) -> dict[str, int]:
    """Write label files for every source file; return {label file: number of blocks}.

    With `prefill`, PII spans (e.g. system predictions) are written as labels
    for the reviewer to confirm, correct or delete.
    """
    all_docs = dataset.load_documents(Path(data_dir))
    groups = documents_by_label_file(all_docs)
    sources = {label_file_name(doc.doc_id): source_name(doc.doc_id) for doc in all_docs}
    known_ids = {doc.doc_id for docs in groups.values() for doc in docs}
    by_doc: dict[str, list[Span]] = {}
    for span in prefill or []:
        if span.is_pii:
            by_doc.setdefault(span.doc_id, []).append(span)
    counts = {}
    for name, docs in groups.items():
        parts = [_preamble(sources[name])]
        for doc in docs:
            _check_exportable(doc, known_ids)
            parts.append(f"### {doc.doc_id}\n{_marked_up(doc, by_doc.get(doc.doc_id, []))}\n")
        target = Path(out_dir) / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("".join(parts), encoding="utf-8", newline="")
        counts[name] = len(docs)
    return counts


# ---------------------------------------------------------------- import


@dataclass(frozen=True)
class Block:
    doc_id: str
    content: str  # labelled text of one document
    first_line: int  # line number of the content's first line in the label file


def split_blocks(content: str, known_ids: set[str], path: str, problems: list[str]) -> list[Block]:
    """Cut a label file into blocks at "### <doc_id>" lines for known ids."""
    headers = [m for m in HEADER_RE.finditer(content) if m.group(1) in known_ids]
    blocks, seen = [], set()
    for index, header in enumerate(headers):
        doc_id = header.group(1)
        line = content.count("\n", 0, header.start()) + 1
        if doc_id in seen:
            problems.append(f"{path}:{line}: second block for {doc_id}")
            continue
        seen.add(doc_id)
        start = header.end() + 1  # skip the header's newline
        end = headers[index + 1].start() if index + 1 < len(headers) else len(content)
        text = content[start:end]
        if text.endswith("\n"):
            text = text[:-1]  # the separator newline written by the exporter
        blocks.append(Block(doc_id, text, line + 1))
    return blocks


def parse_labels(block: Block, path: str, problems: list[str]) -> tuple[str, list[tuple[int, int, str, str, str]]]:
    """Remove the markup of one block; return (plain text, [(start, end, text, type, entity)])."""
    content, out, labels, pos = block.content, [], [], 0
    length = 0

    def where(offset: int) -> str:
        line = block.first_line + content.count("\n", 0, offset)
        return f"{path}:{line}"

    while True:
        opening = content.find(OPEN, pos)
        stray = content.find(CLOSE, pos)
        if stray != -1 and (opening == -1 or stray < opening):
            problems.append(f"{where(stray)}: ']]' without a matching '[['")
            return "", []
        if opening == -1:
            out.append(content[pos:])
            return "".join(out), labels
        out.append(content[pos:opening])
        length += opening - pos
        closing = content.find(CLOSE, opening + len(OPEN))
        if closing == -1:
            problems.append(f"{where(opening)}: '[[' is never closed with ']]'")
            return "", []
        inner = content[opening + len(OPEN) : closing]
        error = _label_problem(inner)
        if error:
            problems.append(f"{where(opening)}: {error} in [[{inner}]]")
            return "", []
        text, type_, entity = inner.rsplit(SEPARATOR, 2)
        labels.append((length, length + len(text), text, type_, entity))
        out.append(text)
        length += len(text)
        pos = closing + len(CLOSE)


def _label_problem(inner: str) -> str | None:
    """Why `inner` (the part between [[ and ]]) is not a valid label, or None."""
    if OPEN in inner:
        return "nested or unclosed '[['"
    parts = inner.rsplit(SEPARATOR, 2)
    if len(parts) != 3:
        return "expected [[exact text|TYPE|ENTITY_ID]]"
    text, type_, entity = parts
    if not text:
        return "empty text"
    if text != text.strip():
        return "label text starts or ends with whitespace"
    if type_ not in PII_TYPES:
        return f"unknown type {type_!r} (allowed: {', '.join(PII_TYPES)})"
    if not ENTITY_ID_RE.fullmatch(entity):
        return f"invalid entity id {entity!r} (use one word without spaces, '|', '[' or ']')"
    return None


def _first_difference(a: str, b: str) -> int:
    for index, (x, y) in enumerate(zip(a, b)):
        if x != y:
            return index
    return min(len(a), len(b))


def _mismatch(block: Block, plain: str, original: str, path: str) -> str:
    offset = _first_difference(plain, original)
    line_no = block.first_line + plain.count("\n", 0, offset)
    found = plain.split("\n")[plain.count("\n", 0, offset)] if plain else ""
    expected = original.split("\n")[original.count("\n", 0, offset)] if original else ""
    hint = ""
    if found.startswith("### "):
        hint = " (a '### ' line with an unknown document id is read as text)"
    elif "\r" in found and "\r" not in expected:
        hint = " (line endings were changed to CRLF)"
    elif len(plain) != len(original) and plain.rstrip("\n") == original.rstrip("\n"):
        hint = " (only newlines at the end of the block differ)"
    return (
        f"{path}:{line_no}: text of {block.doc_id} differs from the original after removing labels{hint}; "
        f"expected {expected!r}, found {found!r}"
    )


def import_labels(data_dir: Path, labels_dir: Path) -> list[Span]:
    """Parse all label files and return gold spans (is_pii=True) in document order.

    Raises LabelError listing every problem as "file:line: message".
    """
    groups = documents_by_label_file(dataset.load_documents(Path(data_dir)))
    problems: list[str] = []
    gold: list[Span] = []
    for name, docs in groups.items():
        path = Path(labels_dir) / name
        if not path.is_file():
            problems.append(f"{path}: label file is missing (run export-labeling first)")
            continue
        with open(path, encoding="utf-8", newline="") as handle:
            content = handle.read()
        by_id = {doc.doc_id: doc for doc in docs}
        blocks = {block.doc_id: block for block in split_blocks(content, set(by_id), str(path), problems)}
        for doc in docs:
            block = blocks.get(doc.doc_id)
            if block is None:
                problems.append(f"{path}: no block for {doc.doc_id} (expected a line '### {doc.doc_id}')")
                continue
            before = len(problems)
            plain, labels = parse_labels(block, str(path), problems)
            if len(problems) > before:
                continue
            if plain != doc.text:
                problems.append(_mismatch(block, plain, doc.text, str(path)))
                continue
            gold.extend(Span(doc.doc_id, s, e, t, type_, True, entity) for s, e, t, type_, entity in labels)
    if problems:
        shown = problems[:MAX_REPORTED_PROBLEMS]
        more = len(problems) - len(shown)
        raise LabelError("\n".join(shown + ([f"... and {more} more"] if more else [])))
    return gold


def write_gold(spans: list[Span], out_path: Path) -> None:
    write_jsonl(Path(out_path), (span.to_gold_dict() for span in spans))
