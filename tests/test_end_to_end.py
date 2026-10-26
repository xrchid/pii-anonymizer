"""End-to-end run of the CLI: generate, detect, anonymize, evaluate, report."""

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from piianon.__main__ import main


class EndToEndTest(unittest.TestCase):
    def test_cli_pipeline(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data, out = root / "data", root / "out"
            with contextlib.redirect_stdout(io.StringIO()) as printed:
                self.assertEqual(main(["generate", "--seed", "42", "--out", str(data)]), 0)
                self.assertEqual(main(["detect", "--data", str(data), "--out", str(out / "pred.jsonl")]), 0)
                predictions = ["--data", str(data), "--predictions", str(out / "pred.jsonl")]
                self.assertEqual(main(["anonymize", *predictions, "--out", str(out / "anon")]), 0)
                self.assertEqual(main(["evaluate", *predictions, "--json", str(out / "metrics.json")]), 0)
                self.assertEqual(main(["report", *predictions, "--out", str(out / "report.md")]), 0)

            self.assertIn("micro avg", printed.getvalue())
            self.assertTrue((out / "pseudonym_key.json").is_file())
            report = (out / "report.md").read_text(encoding="utf-8")
            for heading in ("## Missed PII", "## False positives", "## Clustering"):
                self.assertIn(heading, report)

            metrics = json.loads((out / "metrics.json").read_text(encoding="utf-8"))
            micro = metrics["overlap"]["micro"]
            self.assertGreater(micro["precision"], 0.9)
            self.assertGreater(micro["recall"], 0.9)
            self.assertGreater(metrics["bcubed"]["all_mentions"]["precision"], 0.9)
            tagged = sum(row["tagged_as_pii"] for row in metrics["non_personal"].values())
            self.assertLess(tagged, 10)


if __name__ == "__main__":
    unittest.main()
