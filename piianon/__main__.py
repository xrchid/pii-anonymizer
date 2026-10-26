"""Command line interface.

    python -m piianon generate --seed 42 --out data
    python -m piianon detect --data data --out out/predictions.jsonl
    python -m piianon anonymize --data data --out out/anonymized
    python -m piianon evaluate --data data
    python -m piianon report --data data --out out/error_report.md
    python -m piianon export-labeling --data DIR --out LABELDIR [--prefill out/predictions.jsonl]
    python -m piianon import-labels --data DIR --labels LABELDIR --out DIR/gold.jsonl

`anonymize`, `evaluate` and `report` read --predictions when given and run
detection + resolution in memory otherwise. `evaluate` and `report` need
DIR/gold.jsonl; DIR/decoys.jsonl is optional.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import anonymize, dataset, detect, evaluate, labeling, resolve, synth
from .spans import Decoy, Span, read_decoys, read_spans, write_spans


class CliError(Exception):
    """A problem the user can fix (missing file, bad option)."""


def run_pipeline(data_dir: Path) -> list[Span]:
    """Detect spans in every document and resolve them into clusters."""
    docs = dataset.load_documents(data_dir)
    return resolve.resolve(detect.detect_dataset(docs), docs)


def _predictions(args: argparse.Namespace) -> list[Span]:
    if args.predictions:
        return read_spans(Path(args.predictions))
    return run_pipeline(Path(args.data))


def cmd_generate(args: argparse.Namespace) -> int:
    gold, decoys = synth.generate(Path(args.out), args.seed)
    pii = sum(1 for g in gold if g.is_pii)
    print(f"wrote dataset to {args.out}: {len(gold)} gold spans ({pii} PII), {len(decoys)} decoys")
    return 0


def cmd_detect(args: argparse.Namespace) -> int:
    spans = run_pipeline(Path(args.data))
    write_spans(Path(args.out), spans)
    pii = [s for s in spans if s.is_pii]
    print(f"wrote {len(spans)} spans ({len(pii)} PII in {len({s.entity_id for s in pii})} clusters) to {args.out}")
    return 0


def cmd_anonymize(args: argparse.Namespace) -> int:
    out = Path(args.out)
    key_path = Path(args.key) if args.key else out.parent / "pseudonym_key.json"
    counts = anonymize.anonymize_dataset(Path(args.data), out, _predictions(args), key_path)
    print(
        f"wrote pseudonymized dataset to {out} ({counts['spans_replaced']} spans replaced in "
        f"{counts['documents_changed']} fields); key: {key_path} (store separately)"
    )
    return 0


def _gold(args: argparse.Namespace) -> tuple[list[Span], list[Decoy]]:
    """gold.jsonl (required) and decoys.jsonl (optional; hand-labelled sets have none)."""
    data = Path(args.data)
    gold_path, decoys_path = data / "gold.jsonl", data / "decoys.jsonl"
    if not gold_path.is_file():
        raise CliError(f"{gold_path} not found; create it with `python -m piianon import-labels`")
    decoys = read_decoys(decoys_path) if decoys_path.is_file() else []
    return read_spans(gold_path), decoys


def cmd_evaluate(args: argparse.Namespace) -> int:
    gold, decoys = _gold(args)
    result = evaluate.evaluate(gold, decoys, _predictions(args))
    print(evaluate.metrics_markdown(result), end="")
    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    gold, decoys = _gold(args)
    docs = dataset.load_documents(Path(args.data))
    report = evaluate.error_report(gold, decoys, _predictions(args), docs, limit=args.limit)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report, encoding="utf-8")
    print(f"wrote error report to {out}")
    return 0


def cmd_export_labeling(args: argparse.Namespace) -> int:
    prefill = read_spans(Path(args.prefill)) if args.prefill else None
    counts = labeling.export_labeling(Path(args.data), Path(args.out), prefill)
    for name, blocks in counts.items():
        print(f"{Path(args.out) / name}: {blocks} document(s)")
    return 0


def cmd_import_labels(args: argparse.Namespace) -> int:
    out = Path(args.out) if args.out else Path(args.data) / "gold.jsonl"
    gold = labeling.import_labels(Path(args.data), Path(args.labels))
    labeling.write_gold(gold, out)
    print(f"wrote {len(gold)} gold spans ({len({s.entity_id for s in gold})} entities) to {out}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="piianon", description="PII detection and pseudonymization for business records"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    gen = sub.add_parser("generate", help="write the synthetic dataset with gold annotations")
    gen.add_argument("--seed", type=int, default=42)
    gen.add_argument("--out", default="data")
    gen.set_defaults(func=cmd_generate)

    det = sub.add_parser("detect", help="detect and cluster PII, write predictions.jsonl")
    det.add_argument("--data", default="data")
    det.add_argument("--out", default="out/predictions.jsonl")
    det.set_defaults(func=cmd_detect)

    for name, func, default_out, help_text in (
        ("anonymize", cmd_anonymize, "out/anonymized", "write pseudonymized copies of the dataset"),
        ("evaluate", cmd_evaluate, None, "print metrics against gold.jsonl"),
        ("report", cmd_report, "out/error_report.md", "write a markdown error report"),
    ):
        cmd = sub.add_parser(name, help=help_text)
        cmd.add_argument("--data", default="data")
        cmd.add_argument("--predictions", help="predictions.jsonl from `detect` (default: run detection)")
        if default_out:
            cmd.add_argument("--out", default=default_out)
        cmd.set_defaults(func=func)
    sub.choices["anonymize"].add_argument("--key", help="where to write the pseudonym key (default: next to --out)")
    sub.choices["evaluate"].add_argument("--json", help="also write metrics as JSON to this path")
    sub.choices["report"].add_argument("--limit", type=int, default=40, help="max rows per table")

    exp = sub.add_parser("export-labeling", help="write plain-text files for hand-labelling")
    exp.add_argument("--data", default="data")
    exp.add_argument("--out", required=True, help="folder for the label files")
    exp.add_argument("--prefill", help="predictions.jsonl whose PII spans are written as labels to review")
    exp.set_defaults(func=cmd_export_labeling)

    imp = sub.add_parser("import-labels", help="turn labelled files into gold.jsonl")
    imp.add_argument("--data", default="data")
    imp.add_argument("--labels", required=True, help="folder with the labelled files")
    imp.add_argument("--out", help="output path (default: DATA/gold.jsonl)")
    imp.set_defaults(func=cmd_import_labels)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (CliError, labeling.LabelError, FileNotFoundError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
