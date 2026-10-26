"""Pseudonymization: consistent placeholders across documents, non-PII untouched."""

import csv
import io
import json
import re
import tempfile
import unittest
from pathlib import Path

from piianon import dataset
from piianon.__main__ import run_pipeline
from piianon.anonymize import anonymize_dataset, anonymize_text, cluster_numbers
from piianon.spans import Span, read_spans
from piianon.synth import generate


def read_csv(path: Path) -> list[list[str]]:
    return list(csv.reader(io.StringIO(path.read_text(encoding="utf-8"), newline="")))


def read_json_lines(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


class AnonymizeTextTest(unittest.TestCase):
    def test_replacements_use_cluster_numbers(self) -> None:
        text = "Sasha (o.k@x.example) met Jana."
        spans = [
            Span("d", 0, 5, "Sasha", "PERSON", entity_id="E7"),
            Span("d", 7, 20, "o.k@x.example", "EMAIL", entity_id="E7"),
            Span("d", 26, 30, "Jana", "PERSON", entity_id="E2"),
        ]
        numbers = cluster_numbers(spans)
        self.assertEqual(anonymize_text(text, spans, numbers), "[PERSON_1] ([EMAIL_1]) met [PERSON_2].")

    def test_non_pii_spans_are_kept(self) -> None:
        spans = [Span("d", 0, 7, "info@x.", "EMAIL", is_pii=False, entity_id="")]
        self.assertEqual(anonymize_text("info@x. hello", spans, {}), "info@x. hello")

    def test_mismatched_span_is_an_error(self) -> None:
        with self.assertRaises(ValueError):
            anonymize_text("abc", [Span("d", 0, 2, "xy", "PERSON", entity_id="E1")], {"E1": 1})


class AnonymizeDatasetTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = tempfile.TemporaryDirectory()
        root = Path(cls.tmp.name)
        cls.data, cls.out = root / "data", root / "anon"
        generate(cls.data, seed=42)
        cls.spans = run_pipeline(cls.data)
        anonymize_dataset(cls.data, cls.out, cls.spans, root / "key.json")
        cls.key = json.loads((root / "key.json").read_text(encoding="utf-8"))
        cls.gold = read_spans(cls.data / "gold.jsonl")

    @classmethod
    def tearDownClass(cls) -> None:
        cls.tmp.cleanup()

    def _all_output(self) -> str:
        return "".join(p.read_text(encoding="utf-8") for p in sorted(self.out.rglob("*")) if p.is_file())

    def test_one_person_one_number_across_files(self) -> None:
        # Kovalenko's work e-mail appears in the CRM, an e-mail thread and a ticket signature block.
        placeholders = {name for name, values in self.key.items() if "o.kovalenko@tatra-logistics.example" in values}
        self.assertEqual(len(placeholders), 1)
        number = re.search(r"_(\d+)\]", placeholders.pop()).group(1)
        header, first_row = read_csv(self.out / "crm_export.csv")[:2]
        row = dict(zip(header, first_row))
        self.assertEqual(row["full_name"], f"[PERSON_{number}]")
        self.assertEqual(row["phone"], f"[PHONE_{number}]")
        thread = (self.out / "emails" / "thread_03.txt").read_text(encoding="utf-8")
        self.assertIn(f"[PERSON_{number}] <[EMAIL_{number}]>", thread)
        self.assertIn(f"– [PERSON_{number}]", thread)  # "– Sasha" in the forwarded part

    def test_structure_is_preserved(self) -> None:
        for name in ("crm_export.csv", "invoices.csv"):
            original, anonymized = read_csv(self.data / name), read_csv(self.out / name)
            self.assertEqual([len(r) for r in original], [len(r) for r in anonymized])
            self.assertEqual(original[0], anonymized[0])
        for name in ("tickets.jsonl", "chats.jsonl"):
            original, anonymized = read_json_lines(self.data / name), read_json_lines(self.out / name)
            self.assertEqual([sorted(r) for r in original], [sorted(r) for r in anonymized])

    def test_personal_emails_removed_and_non_personal_kept(self) -> None:
        output = self._all_output()
        detected = {s.text for s in self.spans if s.is_pii and s.type == "EMAIL"}
        for address in detected:
            self.assertNotIn(address, output)
        for kept in ("support@dunajsoft.example", "Tatra Logistics s.r.o.", "ORD-2026-11873", "version 10.2.3.4"):
            self.assertIn(kept, output)

    def test_gold_files_are_not_copied(self) -> None:
        self.assertFalse((self.out / "gold.jsonl").exists())
        self.assertEqual(len(dataset.load_documents(self.out)), len(dataset.load_documents(self.data)))


if __name__ == "__main__":
    unittest.main()
