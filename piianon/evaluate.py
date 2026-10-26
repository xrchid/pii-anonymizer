"""Evaluation against gold annotations, and a markdown error report.

Span metrics compare predicted PII spans (is_pii=True) with gold PII spans:

* exact match: same document, start, end and type;
* overlap match: same document and type, at least one shared character.
  Precision counts predicted spans that overlap a gold span, recall counts
  gold spans that are overlapped by a prediction.

Non-personal items (gold spans with is_pii=False, such as company names and
role mailboxes, plus the decoys in decoys.jsonl) are reported separately:
the question there is how many were wrongly tagged as PII.

Clustering is scored with B-cubed over gold PII mentions. Each gold mention
takes the cluster of the predicted span that overlaps it (same type
preferred); a missed mention counts as a singleton cluster.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from .dataset import Document
from .spans import PII_TYPES, Decoy, Span


@dataclass
class Score:
    n_gold: int = 0
    n_pred: int = 0
    tp_gold: int = 0  # gold spans that were found
    tp_pred: int = 0  # predicted spans that are correct

    @property
    def precision(self) -> float | None:
        return self.tp_pred / self.n_pred if self.n_pred else None

    @property
    def recall(self) -> float | None:
        return self.tp_gold / self.n_gold if self.n_gold else None

    @property
    def f1(self) -> float | None:
        p, r = self.precision, self.recall
        if p is None or r is None or p + r == 0:
            return None if p is None or r is None else 0.0
        return 2 * p * r / (p + r)

    def to_dict(self) -> dict:
        return {
            "gold": self.n_gold,
            "pred": self.n_pred,
            "tp_gold": self.tp_gold,
            "tp_pred": self.tp_pred,
            "precision": self.precision,
            "recall": self.recall,
            "f1": self.f1,
        }


def _by_doc(spans: list[Span]) -> dict[str, list[Span]]:
    index: dict[str, list[Span]] = defaultdict(list)
    for span in spans:
        index[span.doc_id].append(span)
    return index


def _found(span: Span, others: dict[str, list[Span]], mode: str) -> bool:
    for other in others.get(span.doc_id, []):
        if other.type != span.type:
            continue
        if mode == "exact" and (other.start, other.end) == (span.start, span.end):
            return True
        if mode == "overlap" and span.overlaps(other):
            return True
    return False


def span_scores(gold: list[Span], pred: list[Span], mode: str) -> dict[str, Score]:
    """Per-type and micro-averaged scores over PII spans ("exact" or "overlap")."""
    gold_pii = [g for g in gold if g.is_pii]
    pred_pii = [p for p in pred if p.is_pii]
    gold_index, pred_index = _by_doc(gold_pii), _by_doc(pred_pii)
    scores: dict[str, Score] = {t: Score() for t in PII_TYPES}
    for span in gold_pii:
        scores[span.type].n_gold += 1
        scores[span.type].tp_gold += _found(span, pred_index, mode)
    for span in pred_pii:
        scores[span.type].n_pred += 1
        scores[span.type].tp_pred += _found(span, gold_index, mode)
    micro = Score()
    for score in scores.values():
        micro.n_gold += score.n_gold
        micro.n_pred += score.n_pred
        micro.tp_gold += score.tp_gold
        micro.tp_pred += score.tp_pred
    result = {t: s for t, s in scores.items() if s.n_gold or s.n_pred}
    result["micro"] = micro
    return result


def non_personal_items(gold: list[Span], decoys: list[Decoy]) -> list[Decoy]:
    """Gold non-PII spans and decoys, as one list of things not to tag."""
    items = [Decoy(g.doc_id, g.start, g.end, g.text, f"non-personal {g.type}") for g in gold if not g.is_pii]
    return items + list(decoys)


def decoy_report(gold: list[Span], decoys: list[Decoy], pred: list[Span]) -> dict[str, dict[str, int]]:
    """{kind: {"count", "tagged_as_pii", "recognized_non_pii"}} for non-personal items."""
    pred_index = _by_doc(pred)
    table: dict[str, dict[str, int]] = defaultdict(lambda: {"count": 0, "tagged_as_pii": 0, "recognized_non_pii": 0})
    for item in non_personal_items(gold, decoys):
        row = table[item.kind]
        row["count"] += 1
        hits = [p for p in pred_index.get(item.doc_id, []) if p.overlaps(item)]
        row["tagged_as_pii"] += any(p.is_pii for p in hits)
        row["recognized_non_pii"] += any(not p.is_pii for p in hits)
    return dict(sorted(table.items()))


def assign_clusters(gold: list[Span], pred: list[Span]) -> list[str | None]:
    """Predicted cluster for each gold PII mention (None when missed)."""
    pred_index = _by_doc([p for p in pred if p.is_pii])
    assigned: list[str | None] = []
    for span in (g for g in gold if g.is_pii):
        hits = [p for p in pred_index.get(span.doc_id, []) if p.overlaps(span)]
        hits.sort(key=lambda p: (p.type != span.type, p.start))
        assigned.append(hits[0].entity_id if hits else None)
    return assigned


def _bcubed(entities: list[str], clusters: list[str], indices: list[int]) -> dict[str, float | None]:
    if not indices:
        return {"precision": None, "recall": None, "f1": None, "mentions": 0}
    by_cluster: dict[str, set[int]] = defaultdict(set)
    by_entity: dict[str, set[int]] = defaultdict(set)
    for i in indices:
        by_cluster[clusters[i]].add(i)
        by_entity[entities[i]].add(i)
    precision = recall = 0.0
    for i in indices:
        same_cluster, same_entity = by_cluster[clusters[i]], by_entity[entities[i]]
        both = len(same_cluster & same_entity)
        precision += both / len(same_cluster)
        recall += both / len(same_entity)
    precision /= len(indices)
    recall /= len(indices)
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {"precision": precision, "recall": recall, "f1": f1, "mentions": len(indices)}


def bcubed(gold: list[Span], pred: list[Span]) -> dict[str, dict[str, float | None]]:
    """B-cubed over all gold PII mentions and over detected ones only."""
    gold_pii = [g for g in gold if g.is_pii]
    assigned = assign_clusters(gold, pred)
    clusters = [cluster or f"__missed_{i}" for i, cluster in enumerate(assigned)]
    entities = [g.entity_id for g in gold_pii]
    all_indices = list(range(len(gold_pii)))
    detected = [i for i in all_indices if assigned[i] is not None]
    return {
        "all_mentions": _bcubed(entities, clusters, all_indices),
        "detected_mentions": _bcubed(entities, clusters, detected),
    }


def evaluate(gold: list[Span], decoys: list[Decoy], pred: list[Span]) -> dict:
    """All metrics as a JSON-serializable dict."""
    gold_entities = {g.entity_id for g in gold if g.is_pii}
    pred_clusters = {p.entity_id for p in pred if p.is_pii}
    return {
        "exact": {t: s.to_dict() for t, s in span_scores(gold, pred, "exact").items()},
        "overlap": {t: s.to_dict() for t, s in span_scores(gold, pred, "overlap").items()},
        "non_personal": decoy_report(gold, decoys, pred),
        "bcubed": bcubed(gold, pred),
        "entities": {"gold": len(gold_entities), "predicted_clusters": len(pred_clusters)},
    }


# ---------------------------------------------------------------- markdown


def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.3f}"


def _non_personal_table(rows: dict[str, dict[str, int]]) -> list[str]:
    lines = ["| Non-personal item | Count | Tagged as PII | Recognized as non-PII |", "|---|---:|---:|---:|"]
    totals = [0, 0, 0]
    for kind, row in rows.items():
        lines.append(f"| {kind} | {row['count']} | {row['tagged_as_pii']} | {row['recognized_non_pii']} |")
        totals = [totals[0] + row["count"], totals[1] + row["tagged_as_pii"], totals[2] + row["recognized_non_pii"]]
    lines.append(f"| **total** | {totals[0]} | {totals[1]} | {totals[2]} |")
    return lines


def metrics_markdown(result: dict) -> str:
    """Render `evaluate` output as markdown tables."""
    lines = [
        "| Type | Gold | Predicted | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for type_ in [*[t for t in PII_TYPES if t in result["exact"]], "micro"]:
        ex, ov = result["exact"][type_], result["overlap"][type_]
        name = "**micro avg**" if type_ == "micro" else type_
        lines.append(
            f"| {name} | {ex['gold']} | {ex['pred']} | {_pct(ex['precision'])} | {_pct(ex['recall'])} | "
            f"{_pct(ex['f1'])} | {_pct(ov['precision'])} | {_pct(ov['recall'])} | {_pct(ov['f1'])} |"
        )
    if result["non_personal"]:
        lines += ["", *_non_personal_table(result["non_personal"])]
    else:
        lines += ["", "No decoys.jsonl and no non-PII gold spans: non-personal table skipped."]
    lines += ["", "| Clustering (B-cubed) | Mentions | Precision | Recall | F1 |", "|---|---:|---:|---:|---:|"]
    labels = {
        "all_mentions": "all gold PII mentions (missed = singleton)",
        "detected_mentions": "detected gold PII mentions",
    }
    for key, label in labels.items():
        row = result["bcubed"][key]
        lines.append(
            f"| {label} | {row['mentions']} | {_pct(row['precision'])} | {_pct(row['recall'])} | {_pct(row['f1'])} |"
        )
    ent = result["entities"]
    lines += ["", f"Gold PII entities: {ent['gold']}; predicted clusters: {ent['predicted_clusters']}."]
    return "\n".join(lines) + "\n"


def _context(doc: Document | None, start: int, end: int, width: int = 45) -> str:
    if doc is None:
        return ""
    text = doc.text
    snippet = f"{text[max(0, start - width) : start]}**[{text[start:end]}]**{text[end : end + width]}"
    return snippet.replace("\n", " ⏎ ").replace("|", "\\|")


def _cell(value: str) -> str:
    return value.replace("\n", " ⏎ ").replace("|", "\\|")


def error_report(gold: list[Span], decoys: list[Decoy], pred: list[Span], docs: list[Document], limit: int = 40) -> str:
    """Markdown report: metrics, missed spans, false positives, type and
    boundary mismatches, and clustering splits/merges."""
    doc_map = {d.doc_id: d for d in docs}
    order = {d.doc_id: i for i, d in enumerate(docs)}
    gold_pii = [g for g in gold if g.is_pii]
    pred_pii = [p for p in pred if p.is_pii]
    gold_index, pred_index = _by_doc(gold_pii), _by_doc(pred_pii)

    def position(span: Span) -> tuple[int, int]:
        return order.get(span.doc_id, 0), span.start

    out = ["# Error report", "", "## Metrics", "", metrics_markdown(evaluate(gold, decoys, pred))]

    missed = [g for g in gold_pii if not _found(g, pred_index, "overlap")]
    out += [f"## Missed PII ({len(missed)} gold spans with no overlapping prediction of the same type)", ""]
    out += ["| Type | Document | Gold text | Predicted instead | Context |", "|---|---|---|---|---|"]
    for g in sorted(missed, key=lambda s: (s.type, position(s)))[:limit]:
        instead = ", ".join(p.type for p in pred_index.get(g.doc_id, []) if p.overlaps(g)) or "-"
        context = _context(doc_map.get(g.doc_id), g.start, g.end)
        out.append(f"| {g.type} | {g.doc_id} | {_cell(g.text)} | {instead} | {context} |")

    items = non_personal_items(gold, decoys)
    item_index: dict[str, list[Decoy]] = defaultdict(list)
    for item in items:
        item_index[item.doc_id].append(item)
    false_pos = [p for p in pred_pii if not _found(p, gold_index, "overlap")]
    out += [
        "",
        f"## False positives ({len(false_pos)} predicted PII spans with no overlapping gold span of the same type)",
        "",
    ]
    out += ["| Type | Document | Text | Rule | Overlaps | Context |", "|---|---|---|---|---|---|"]
    for p in sorted(false_pos, key=lambda s: (s.type, position(s)))[:limit]:
        hits = [i.kind for i in item_index.get(p.doc_id, []) if p.overlaps(i)]
        hits += [f"gold {g.type}" for g in gold_index.get(p.doc_id, []) if p.overlaps(g)]
        context = _context(doc_map.get(p.doc_id), p.start, p.end)
        out.append(f"| {p.type} | {p.doc_id} | {_cell(p.text)} | {p.source} | {', '.join(hits) or '-'} | {context} |")

    boundary = [
        (g, p)
        for g in gold_pii
        for p in pred_index.get(g.doc_id, [])
        if p.type == g.type and p.overlaps(g) and (p.start, p.end) != (g.start, g.end)
    ]
    out += ["", f"## Boundary differences ({len(boundary)} overlapping same-type pairs that are not exact)", ""]
    out += ["| Type | Document | Gold | Predicted | Rule |", "|---|---|---|---|---|"]
    for g, p in sorted(boundary, key=lambda gp: position(gp[0]))[:limit]:
        out.append(f"| {g.type} | {g.doc_id} | {_cell(g.text)} | {_cell(p.text)} | {p.source} |")

    out += ["", *_clustering_section(gold_pii, pred_pii, gold, pred)]
    return "\n".join(out) + "\n"


def _clustering_section(gold_pii: list[Span], pred_pii: list[Span], gold: list[Span], pred: list[Span]) -> list[str]:
    assigned = assign_clusters(gold, pred)
    entity_clusters: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    cluster_entities: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    for g, cluster in zip(gold_pii, assigned):
        if cluster is None:
            continue
        entity_clusters[g.entity_id][cluster].append(g.text)
        cluster_entities[cluster][g.entity_id].append(g.text)

    def forms(texts: list[str]) -> str:
        unique = sorted(set(texts))
        shown = ", ".join(_cell(t) for t in unique[:6])
        return shown + (f" (+{len(unique) - 6} more)" if len(unique) > 6 else "")

    lines = ["## Clustering: gold entities split over several predicted clusters", ""]
    lines += ["| Gold entity | Predicted clusters (mentions) |", "|---|---|"]
    for entity in sorted(entity_clusters):
        clusters = entity_clusters[entity]
        if len(clusters) > 1:
            parts = [f"{c}: {forms(t)}" for c, t in sorted(clusters.items(), key=lambda kv: -len(kv[1]))]
            lines.append(f"| {entity} | {' / '.join(parts)} |")
    lines += ["", "## Clustering: predicted clusters that mix gold entities", ""]
    lines += ["| Predicted cluster | Gold entities (mentions) |", "|---|---|"]
    for cluster in sorted(cluster_entities, key=lambda c: int(c[1:]) if c[1:].isdigit() else 0):
        entities = cluster_entities[cluster]
        if len(entities) > 1:
            parts = [f"{e}: {forms(t)}" for e, t in sorted(entities.items())]
            lines.append(f"| {cluster} | {' / '.join(parts)} |")
    return lines
