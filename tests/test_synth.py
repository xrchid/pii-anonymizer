"""Generator: exact gold offsets, determinism, annotation invariants."""

import filecmp
import tempfile
import unittest
from pathlib import Path

from piianon import dataset
from piianon.detect import iban_is_valid
from piianon.spans import PII_TYPES, read_decoys, read_spans
from piianon.synth import generate


def phone_texts(data: Path) -> set[str]:
    return {s.text for s in read_spans(data / "gold.jsonl") if s.type == "PHONE"}


class SynthTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = tempfile.TemporaryDirectory()
        cls.data = Path(cls.tmp.name) / "data"
        generate(cls.data, seed=42)
        cls.gold = read_spans(cls.data / "gold.jsonl")
        cls.decoys = read_decoys(cls.data / "decoys.jsonl")
        cls.docs = {doc.doc_id: doc for doc in dataset.load_documents(cls.data)}

    @classmethod
    def tearDownClass(cls) -> None:
        cls.tmp.cleanup()

    def test_five_document_kinds_exist(self) -> None:
        for name in ("crm_export.csv", "tickets.jsonl", "chats.jsonl", "invoices.csv"):
            self.assertTrue((self.data / name).is_file(), name)
        self.assertGreaterEqual(len(dataset.email_files(self.data)), 5)

    def test_gold_offsets_match_text_after_reloading_files(self) -> None:
        for span in self.gold:
            self.assertEqual(self.docs[span.doc_id].text[span.start : span.end], span.text, span)
        for item in self.decoys:
            self.assertEqual(self.docs[item.doc_id].text[item.start : item.end], item.text, item)

    def test_gold_spans_do_not_overlap(self) -> None:
        by_doc: dict[str, list] = {}
        for span in self.gold:
            by_doc.setdefault(span.doc_id, []).append(span)
        for spans in by_doc.values():
            spans.sort(key=lambda s: s.start)
            for left, right in zip(spans, spans[1:]):
                self.assertLessEqual(left.end, right.start, (left, right))

    def test_annotation_invariants(self) -> None:
        for span in self.gold:
            self.assertIn(span.type, PII_TYPES)
            self.assertTrue(span.entity_id)
            if span.is_pii:
                self.assertTrue(span.entity_id.startswith("P"), span)  # personal data belongs to a person
        sole_traders = [s for s in self.gold if s.type == "ORGANIZATION" and s.is_pii]
        self.assertTrue(sole_traders)
        self.assertTrue(all(s.entity_id in ("P03", "P07") for s in sole_traders))

    def test_hard_cases_are_present(self) -> None:
        p01 = {s.text for s in self.gold if s.entity_id == "P01" and s.type == "PERSON"}
        self.assertTrue({"Oleksandr Kovalenko", "Alexander Kovalenko", "Sasha", "O. Kovalenko"} <= p01)
        self.assertIn("Наталія Шевчук", {s.text for s in self.gold})
        self.assertIn("VERSION_STRING", {d.kind for d in self.decoys})
        self.assertIn("support@dunajsoft.example", {s.text for s in self.gold if not s.is_pii})

    def test_ibans_are_checksum_valid(self) -> None:
        ibans = [s.text for s in self.gold if s.type == "IBAN"]
        self.assertTrue(ibans)
        for iban in ibans:
            self.assertTrue(iban_is_valid(iban), iban)

    def test_same_seed_same_bytes_other_seed_other_values(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            again, other = Path(tmp) / "again", Path(tmp) / "other"
            generate(again, seed=42)
            generate(other, seed=7)
            files = ["crm_export.csv", "tickets.jsonl", "chats.jsonl", "invoices.csv", "gold.jsonl", "decoys.jsonl"]
            match, mismatch, errors = filecmp.cmpfiles(self.data, again, files, shallow=False)
            self.assertEqual((mismatch, errors), ([], []))
            self.assertNotEqual(phone_texts(self.data), phone_texts(other))


if __name__ == "__main__":
    unittest.main()
