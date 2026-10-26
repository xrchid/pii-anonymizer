"""Hand-labelling workflow: export, inline markup, import, and every error case."""

import contextlib
import io
import shutil
import tempfile
import unittest
from pathlib import Path

from piianon.__main__ import main
from piianon.labeling import LabelError, export_labeling, import_labels
from piianon.spans import read_spans
from piianon.synth import generate


def edit(path: Path, old: str, new: str) -> int:
    """Replace the first `old` in a label file; return its 1-based line number."""
    text = path.read_text(encoding="utf-8")
    index = text.index(old)
    path.write_text(text[:index] + new + text[index + len(old) :], encoding="utf-8")
    return text.count("\n", 0, index) + 1


def span_key(span):
    return (span.doc_id, span.start, span.end, span.text, span.type, span.entity_id)


class LabelingTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.tmp.name)
        cls.data = cls.root / "data"
        generate(cls.data, seed=42)
        cls.gold = [s for s in read_spans(cls.data / "gold.jsonl") if s.is_pii]
        cls.blank = cls.root / "blank"
        export_labeling(cls.data, cls.blank)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.tmp.cleanup()

    def labels(self) -> Path:
        """A fresh copy of the unlabelled export for one test to edit."""
        target = Path(tempfile.mkdtemp(dir=self.root))
        shutil.copytree(self.blank, target / "labels")
        return target / "labels"

    def assert_problem(self, labels: Path, *fragments: str) -> str:
        with self.assertRaises(LabelError) as caught:
            import_labels(self.data, labels)
        message = str(caught.exception)
        for fragment in fragments:
            self.assertIn(fragment, message)
        return message

    # ------------------------------------------------------------ export and round trip

    def test_export_writes_one_file_per_source_with_exact_blocks(self) -> None:
        names = sorted(str(p.relative_to(self.blank)) for p in self.blank.rglob("*.txt"))
        self.assertEqual(names[:4], ["chats.txt", "crm_export.txt", "emails/thread_01.txt", "emails/thread_02.txt"])
        self.assertIn("invoices.txt", names)
        self.assertIn("tickets.txt", names)
        crm = (self.blank / "crm_export.txt").read_text(encoding="utf-8")
        self.assertIn("### crm_export.csv:1:full_name\nOleksandr Kovalenko\n### crm_export.csv:1:email\n", crm)
        self.assertNotIn("### crm_export.csv:10:company\n", crm)  # empty cell: cannot hold PII

    def test_unlabelled_files_import_as_empty_gold(self) -> None:
        self.assertEqual(import_labels(self.data, self.blank), [])

    def test_round_trip_reproduces_generator_gold(self) -> None:
        labels = self.root / "prefilled"
        export_labeling(self.data, labels, prefill=self.gold)
        self.assertIn("[[Oleksandr Kovalenko|PERSON|P01]]", (labels / "crm_export.txt").read_text(encoding="utf-8"))
        imported = import_labels(self.data, labels)
        self.assertEqual(sorted(map(span_key, imported)), sorted(map(span_key, self.gold)))
        self.assertTrue(all(span.is_pii for span in imported))

    def test_hand_written_labels_get_offsets(self) -> None:
        labels = self.labels()
        edit(labels / "crm_export.txt", "Emily Carter\n", "[[Emily Carter|PERSON|P1]]\n")
        edit(
            labels / "crm_export.txt", "emily.carter@brightwell.example", "[[emily.carter@brightwell.example|EMAIL|P1]]"
        )
        spans = import_labels(self.data, labels)
        self.assertEqual(
            [(s.text, s.type, s.entity_id, s.start) for s in spans],
            [("Emily Carter", "PERSON", "P1", 0), ("emily.carter@brightwell.example", "EMAIL", "P1", 0)],
        )

    def test_label_spanning_two_lines(self) -> None:
        data = self.root / "multiline"
        (data / "emails").mkdir(parents=True)
        (data / "emails" / "thread_01.txt").write_text("Regards,\nJana\nHlavná 12\n040 01 Košice\n", encoding="utf-8")
        labels = data.parent / "multiline_labels"
        export_labeling(data, labels)
        edit(labels / "emails" / "thread_01.txt", "Hlavná 12\n040 01 Košice", "[[Hlavná 12\n040 01 Košice|ADDRESS|J]]")
        (span,) = import_labels(data, labels)
        self.assertEqual((span.start, span.end, span.text), (14, 37, "Hlavná 12\n040 01 Košice"))

    # ------------------------------------------------------------ error cases

    def test_unknown_type(self) -> None:
        labels = self.labels()
        line = edit(labels / "crm_export.txt", "Oleksandr Kovalenko", "[[Oleksandr Kovalenko|NAME|P1]]")
        self.assert_problem(labels, f"crm_export.txt:{line}:", "unknown type 'NAME'")

    def test_unclosed_label(self) -> None:
        labels = self.labels()
        line = edit(labels / "crm_export.txt", "Oleksandr Kovalenko", "[[Oleksandr Kovalenko|PERSON|P1")
        self.assert_problem(labels, f"crm_export.txt:{line}:", "never closed")

    def test_missing_field(self) -> None:
        labels = self.labels()
        line = edit(labels / "invoices.txt", "Katarína Bieliková", "[[Katarína Bieliková|PERSON]]")
        self.assert_problem(labels, f"invoices.txt:{line}:", "expected [[exact text|TYPE|ENTITY_ID]]")

    def test_stray_closing_brackets(self) -> None:
        labels = self.labels()
        line = edit(labels / "tickets.txt", "Hello Lucia", "Hello Lucia]]")
        self.assert_problem(labels, f"tickets.txt:{line}:", "']]' without a matching '[['")

    def test_nested_label(self) -> None:
        labels = self.labels()
        line = edit(labels / "crm_export.txt", "Oleksandr Kovalenko", "[[Oleksandr [[Kovalenko|PERSON|P1]]")
        self.assert_problem(labels, f"crm_export.txt:{line}:", "nested or unclosed")

    def test_invalid_entity_id_and_whitespace(self) -> None:
        labels = self.labels()
        line_a = edit(labels / "crm_export.txt", "Oleksandr Kovalenko", "[[Oleksandr Kovalenko|PERSON|P 1]]")
        line_b = edit(labels / "crm_export.txt", "Oleksandr Bondarenko", "[[Oleksandr Bondarenko |PERSON|P2]]")
        message = self.assert_problem(labels, "invalid entity id 'P 1'", "starts or ends with whitespace")
        self.assertIn(f"crm_export.txt:{line_a}:", message)
        self.assertIn(f"crm_export.txt:{line_b}:", message)  # all problems are reported, not only the first

    def test_changed_text_outside_labels(self) -> None:
        labels = self.labels()
        line = edit(labels / "emails" / "thread_01.txt", "thanks for the quote", "thanks for the qoute")
        self.assert_problem(labels, f"thread_01.txt:{line}:", "differs from the original", "qoute")

    def test_changed_text_inside_label(self) -> None:
        labels = self.labels()
        line = edit(labels / "crm_export.txt", "Oleksandr Kovalenko", "[[Oleksandr Kovalenko Jr|PERSON|P1]]")
        self.assert_problem(labels, f"crm_export.txt:{line}:", "differs from the original")

    def test_removed_final_newline(self) -> None:
        labels = self.labels()
        path = labels / "emails" / "thread_02.txt"
        path.write_text(path.read_text(encoding="utf-8").rstrip("\n"), encoding="utf-8")
        self.assert_problem(labels, "thread_02.txt:", "only newlines at the end of the block differ")

    def test_missing_and_duplicate_blocks(self) -> None:
        labels = self.labels()
        edit(labels / "invoices.txt", "### invoices.csv:9:amount\n", "")
        path = labels / "chats.txt"
        text = path.read_text(encoding="utf-8")
        path.write_text(text + "### chats.jsonl:1:chat_id\nCH-001\n", encoding="utf-8")
        line = text.count("\n") + 1
        self.assert_problem(
            labels, "no block for invoices.csv:9:amount", f"chats.txt:{line}: second block for chats.jsonl:1:chat_id"
        )

    def test_missing_label_file(self) -> None:
        labels = self.labels()
        (labels / "tickets.txt").unlink()
        self.assert_problem(labels, "tickets.txt: label file is missing")

    def test_export_refuses_text_with_markup_characters(self) -> None:
        data = self.root / "brackets"
        (data / "emails").mkdir(parents=True)
        (data / "emails" / "thread_01.txt").write_text("see [[wiki]] page\n", encoding="utf-8")
        with self.assertRaises(LabelError):
            export_labeling(data, self.root / "brackets_labels")


class CommandLineTest(unittest.TestCase):
    def test_import_error_exit_code_and_evaluate_without_decoys(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data, labels = root / "data", root / "labels"
            generate(data, seed=1)
            (data / "decoys.jsonl").unlink()
            gold = [s for s in read_spans(data / "gold.jsonl") if s.is_pii]
            (data / "gold.jsonl").unlink()
            out, err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                self.assertEqual(main(["evaluate", "--data", str(data)]), 1)  # no gold yet
                export_labeling(data, labels, prefill=gold)
                edit(labels / "crm_export.txt", "|PERSON|P01]]", "|NAME|P01]]")
                self.assertEqual(main(["import-labels", "--data", str(data), "--labels", str(labels)]), 1)
                edit(labels / "crm_export.txt", "|NAME|P01]]", "|PERSON|P01]]")
                self.assertEqual(main(["import-labels", "--data", str(data), "--labels", str(labels)]), 0)
                self.assertEqual(main(["evaluate", "--data", str(data)]), 0)
                self.assertEqual(main(["report", "--data", str(data), "--out", str(root / "report.md")]), 0)
            self.assertIn("gold.jsonl not found", err.getvalue())
            self.assertIn("unknown type 'NAME'", err.getvalue())
            self.assertIn("non-personal table skipped", out.getvalue())
            self.assertIn("micro avg", out.getvalue())
            self.assertIn("## Missed PII", (root / "report.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
