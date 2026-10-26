"""Command line interface.

    python -m piianon generate --seed 42 --out data
    python -m piianon detect --data data --out out/predictions.jsonl
    python -m piianon anonymize --data data --out out/anonymized
    python -m piianon evaluate --data data
    python -m piianon report --data data --out out/error_report.md

`anonymize`, `evaluate` and `report` read --predictions when given and run
detection + resolution in memory otherwise.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import anonymize, dataset, detect, evaluate, resolve, synth
from .spans import Span, read_decoys, read_spans, write_spans


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


def _gold(args: argparse.Namespace) -> tuple[list[Span], list]:
    data = Path(args.data)
    return read_spans(data / "gold.jsonl"), read_decoys(data / "decoys.jsonl")


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
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
