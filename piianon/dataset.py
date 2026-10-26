"""Read and rewrite the five document kinds as a flat list of text fields.

Every string value in the dataset becomes one `Document`:

* CSV files: one document per cell, id ``crm_export.csv:3:notes`` (data row 3).
* JSONL files: one document per string leaf, id ``chats.jsonl:2:messages.4.text``.
* E-mail files: one document per file, id ``emails/thread_01.txt``.

Gold offsets, detector output and anonymization all refer to these ids, and
`transform_files` rebuilds each file with every field passed through a
function, so the anonymized copy keeps the original structure.
"""

from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

CRM_FILE = "crm_export.csv"
TICKETS_FILE = "tickets.jsonl"
EMAIL_DIR = "emails"
CHATS_FILE = "chats.jsonl"
INVOICES_FILE = "invoices.csv"
CSV_FILES: tuple[str, ...] = (CRM_FILE, INVOICES_FILE)
JSONL_FILES: tuple[str, ...] = (TICKETS_FILE, CHATS_FILE)

# Fields that hold free text written by people (as opposed to one value per cell).
FREE_TEXT_FIELDS: frozenset[str] = frozenset({"notes", "subject", "body", "text", ""})


@dataclass(frozen=True)
class Document:
    """One text field of the dataset.

    `record` identifies the row, JSONL line or e-mail file the field belongs
    to; `field` is the column or key name ("" for a whole e-mail file).
    """

    doc_id: str
    text: str
    record: str
    field: str

    @property
    def is_free_text(self) -> bool:
        return self.field in FREE_TEXT_FIELDS


def csv_doc_id(name: str, row: int, column: str) -> str:
    return f"{name}:{row}:{column}"


def jsonl_doc_id(name: str, line: int, path: str) -> str:
    return f"{name}:{line}:{path}"


def email_doc_id(filename: str) -> str:
    return f"{EMAIL_DIR}/{filename}"


TextFn = Callable[[Document], str]


def _read_text(path: Path) -> str:
    with open(path, encoding="utf-8", newline="") as handle:
        return handle.read()


def _transform_csv(content: str, name: str, fn: TextFn) -> str:
    rows = list(csv.reader(io.StringIO(content, newline="")))
    header, body = rows[0], rows[1:]
    out = io.StringIO(newline="")
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(header)
    for row_no, row in enumerate(body, start=1):
        record = f"{name}:{row_no}"
        new_row = []
        for column, value in zip(header, row):
            doc = Document(csv_doc_id(name, row_no, column), value, record, column)
            new_row.append(fn(doc))
        writer.writerow(new_row)
    return out.getvalue()


def _transform_json_value(value: Any, path: str, name: str, line: int, fn: TextFn) -> Any:
    """Recursively apply `fn` to every string leaf, keeping dict and list shape."""
    if isinstance(value, str):
        field = path.rsplit(".", 1)[-1]
        return fn(Document(jsonl_doc_id(name, line, path), value, f"{name}:{line}", field))
    if isinstance(value, dict):
        return {
            key: _transform_json_value(item, f"{path}.{key}" if path else key, name, line, fn)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_transform_json_value(item, f"{path}.{index}", name, line, fn) for index, item in enumerate(value)]
    return value


def _transform_jsonl(content: str, name: str, fn: TextFn) -> str:
    out_lines = []
    # split("\n") rather than splitlines(): the latter also breaks on U+2028.
    lines = [line for line in content.split("\n") if line.strip()]
    for line_no, line in enumerate(lines, start=1):
        record = json.loads(line)
        new_record = _transform_json_value(record, "", name, line_no, fn)
        out_lines.append(json.dumps(new_record, ensure_ascii=False))
    return "".join(line + "\n" for line in out_lines)


def email_files(data_dir: Path) -> list[Path]:
    return sorted((data_dir / EMAIL_DIR).glob("*.txt"))


def transform_files(data_dir: Path, fn: TextFn) -> dict[str, str]:
    """Apply `fn` to every text field; return {relative path: new file content}.

    Files are visited in a fixed order (CRM, tickets, e-mails, chats,
    invoices) so document order is deterministic.
    """
    outputs: dict[str, str] = {}
    outputs[CRM_FILE] = _transform_csv(_read_text(data_dir / CRM_FILE), CRM_FILE, fn)
    outputs[TICKETS_FILE] = _transform_jsonl(_read_text(data_dir / TICKETS_FILE), TICKETS_FILE, fn)
    for path in email_files(data_dir):
        doc_id = email_doc_id(path.name)
        outputs[doc_id] = fn(Document(doc_id, _read_text(path), doc_id, ""))
    outputs[CHATS_FILE] = _transform_jsonl(_read_text(data_dir / CHATS_FILE), CHATS_FILE, fn)
    outputs[INVOICES_FILE] = _transform_csv(_read_text(data_dir / INVOICES_FILE), INVOICES_FILE, fn)
    return outputs


def load_documents(data_dir: Path) -> list[Document]:
    """Return every text field of the dataset in deterministic order."""
    docs: list[Document] = []

    def collect(doc: Document) -> str:
        docs.append(doc)
        return doc.text

    transform_files(Path(data_dir), collect)
    return docs


def write_outputs(out_dir: Path, outputs: dict[str, str]) -> None:
    """Write {relative path: content} produced by `transform_files`."""
    for rel_path, content in outputs.items():
        target = Path(out_dir) / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8", newline="\n")


def write_csv(path: Path, header: list[str], rows: list[list[str]]) -> None:
    out = io.StringIO(newline="")
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(header)
    writer.writerows(rows)
    path.write_text(out.getvalue(), encoding="utf-8", newline="\n")


def write_jsonl_records(path: Path, records: list[dict]) -> None:
    lines = [json.dumps(record, ensure_ascii=False) for record in records]
    path.write_text("".join(line + "\n" for line in lines), encoding="utf-8", newline="\n")
