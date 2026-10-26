"""Entity resolution: group mentions that refer to the same person.

Pipeline (each step only adds links; `Clusters.union` refuses a link that
would put two incompatible names in one cluster):

1. Equal values: same e-mail, phone (E.164), IBAN, customer number, IP,
   address, or same full name after normalization.
2. Structured records: the cells of one CSV row describe one party.
3. "Name <address>" pairs in e-mail headers.
4. Signature blocks: identifiers under a name belong to that name.
   First-person sentences of the newest message ("my date of birth is ...")
   belong to the person who signed it.
5. Chat handles: identifiers written by one handle belong together, and to
   the name the handle introduced itself with ("Sasha here").
6. E-mail local parts: o.kovalenko@ -> (initial o, surname kovalenko).
7. Partial names (initial + surname, surname only, first name or nickname
   only) join a full name only when exactly one candidate exists, first in
   the same record, then in the whole dataset.

Name comparison uses `normalize_name`: case folding, Ukrainian Cyrillic to
Latin transliteration and removal of diacritics, so "Олександр Коваленко",
"Oleksandr Kovalenko" and "OLEKSANDR KOVALENKO" share one key.
"""

from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass, replace

from . import layout, lexicon
from .dataset import CHATS_FILE, CSV_FILES, Document
from .spans import Span

# ---------------------------------------------------------------- normalization


def transliterate(text: str) -> str:
    """Transliterate Ukrainian Cyrillic to Latin (2010 national system), lower case.

    >>> transliterate("Олександр Коваленко")
    'oleksandr kovalenko'
    """
    out: list[str] = []
    prev_letter = False
    prev_char = ""
    for char in text.casefold():
        if char in lexicon.UK_TRANSLIT:
            inner, initial = lexicon.UK_TRANSLIT[char]
            latin = inner if prev_letter else initial
            if char == "г" and prev_char == "з":  # "зг" -> "zgh" to keep it apart from "ж"
                latin = "gh"
            out.append(latin)
        else:
            out.append(char)
        prev_letter = char.isalpha() or char in "'’ʼ"
        prev_char = char
    return "".join(out)


def strip_diacritics(text: str) -> str:
    """'Ľubomír Šťastný' -> 'Lubomir Stastny'."""
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def normalize_name(text: str) -> str:
    """Comparable form of a name: lower-case ASCII letters and single spaces."""
    latin = strip_diacritics(transliterate(text))
    letters = re.sub(r"[^a-z]+", " ", latin)
    return " ".join(letters.split())


def canonical_first_name(word: str) -> str | None:
    """Map a given name or nickname to its canonical form ('Sasha' -> 'oleksandr')."""
    return lexicon.CANONICAL_FIRST.get(normalize_name(word))


def initials_of(canonical_first: str) -> set[str]:
    """Initials a person with this given name may sign with ('oleksandr' -> {o, a, s})."""
    variants = lexicon.NAME_GROUPS.get(canonical_first, (canonical_first,))
    return {variant[0] for variant in variants} | {canonical_first[0]}


# ---------------------------------------------------------------- name keys


@dataclass(frozen=True)
class NameKey:
    """What a mention says about a person's name. Any part may be unknown."""

    first: str | None = None  # canonical given name
    surname: str | None = None  # normalized surname
    initial: str | None = None  # given-name initial, as in "O. Kovalenko"
    word: str | None = None  # a single name word of unknown role ("Radim", "Kovalenko")

    @property
    def is_full(self) -> bool:
        return bool(self.first and self.surname)


_SOLE_TRADER_MARKERS = {"fop"}  # "FOP" / "ФОП" before a Ukrainian sole trader's name


def name_key(text: str) -> NameKey | None:
    """Parse a written name into a NameKey.

    "O. Kovalenko" -> (initial o, surname kovalenko); "Мельник Дмитро" ->
    (dmytro, melnyk) because the gazetteer knows which word is the given name.
    """
    words = [w for w in normalize_name(text).split() if w not in lexicon.TITLES and w not in _SOLE_TRADER_MARKERS]
    first: str | None = None
    initial: str | None = None
    rest: list[str] = []
    for word in words:
        if len(word) == 1:
            initial = initial or word
        elif first is None and word in lexicon.CANONICAL_FIRST:
            first = lexicon.CANONICAL_FIRST[word]
        else:
            rest.append(word)
    if first is None and initial is None and len(rest) == 1:
        return NameKey(word=rest[0])  # one word: could be a given name or a surname
    surname = rest[-1] if rest else None
    if first is None and initial is None and len(rest) >= 2:
        first = rest[0]  # unknown given name, e.g. from an e-mail header
    if first is None and surname is None:
        return None
    return NameKey(first, surname, initial)


def email_name_key(address: str) -> NameKey | None:
    """Read a name from an e-mail local part.

    Handles first.last, f.last, last.first and nickname.last; digits are
    ignored ("sasha.k92" -> given name only). Role mailboxes return None.
    """
    local = address.split("@", 1)[0].casefold()
    if local in lexicon.ROLE_LOCAL_PARTS:
        return None
    parts = [re.sub(r"\d+", "", part) for part in re.split(r"[._\-+]+", local)]
    parts = [part for part in parts if part]
    if not parts:
        return None
    canon = lexicon.CANONICAL_FIRST
    if len(parts) == 1:
        return NameKey(first=canon[parts[0]]) if parts[0] in canon else None
    a, b = parts[0], parts[-1]
    if len(a) == 1 and len(b) > 1:
        return NameKey(surname=b, initial=a)
    if len(b) == 1:
        return NameKey(first=canon[a]) if a in canon else None
    if a in canon:
        return NameKey(first=canon[a], surname=b)
    if b in canon:
        return NameKey(first=canon[b], surname=a)
    return None


def compatible(a: NameKey, b: NameKey) -> bool:
    """False when the two keys cannot describe the same person."""
    if a.word and b.is_full and a.word not in (b.first, b.surname):
        return False
    if b.word and a.is_full and b.word not in (a.first, a.surname):
        return False
    if a.surname and b.surname and a.surname != b.surname:
        return False
    if a.first and b.first and a.first != b.first:
        return False
    if a.initial and b.first and a.initial not in initials_of(b.first):
        return False
    if b.initial and a.first and b.initial not in initials_of(a.first):
        return False
    return True


def matches(partial: NameKey, full: NameKey) -> bool:
    """True when every part known in `partial` agrees with the full name."""
    if partial.word and partial.word not in (full.first, full.surname):
        return False
    if partial.surname and partial.surname != full.surname:
        return False
    if partial.first and partial.first != full.first:
        return False
    if partial.initial and full.first and partial.initial not in initials_of(full.first):
        return False
    return True


def mention_name_key(span: Span) -> NameKey | None:
    """Name key of a PERSON, sole-trader ORGANIZATION or personal EMAIL mention."""
    if span.type == "PERSON":
        return name_key(span.text)
    if span.type == "ORGANIZATION" and span.is_pii:
        person_part = re.split(r"\s[–-]\s", span.text)[0]
        return name_key(person_part)
    if span.type == "EMAIL" and span.is_pii:
        return email_name_key(span.text)
    return None


# ---------------------------------------------------------------- clustering


class Clusters:
    """Union-find over mention indices with a cannot-link check on names.

    `keys[root]` holds every name key seen in the cluster; two clusters are
    merged only if all their keys are pairwise compatible. `anchors[root]`
    holds full names that came from PERSON/ORGANIZATION mentions; partial
    mentions are matched against these.
    """

    def __init__(self, mentions: list[Span]) -> None:
        self.parent = list(range(len(mentions)))
        self.keys: dict[int, list[NameKey]] = {}
        self.anchors: dict[int, list[NameKey]] = {}
        for index, span in enumerate(mentions):
            key = mention_name_key(span)
            self.keys[index] = [key] if key else []
            is_name = span.type in ("PERSON", "ORGANIZATION")
            self.anchors[index] = [key] if key and key.is_full and is_name else []

    def find(self, index: int) -> int:
        root = index
        while self.parent[root] != root:
            root = self.parent[root]
        while self.parent[index] != root:  # path compression: point straight at the root
            next_index = self.parent[index]
            self.parent[index] = root
            index = next_index
        return root

    def can_union(self, a: int, b: int) -> bool:
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return True
        return all(compatible(x, y) for x in self.keys[ra] for y in self.keys[rb])

    def union(self, a: int, b: int) -> bool:
        """Merge the clusters of a and b; return False if names conflict."""
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return True
        if not self.can_union(ra, rb):
            return False
        root, child = min(ra, rb), max(ra, rb)
        self.parent[child] = root
        self.keys[root].extend(self.keys.pop(child))
        self.anchors[root].extend(self.anchors.pop(child))
        return True


def _value_key(span: Span) -> tuple[str, ...] | None:
    """Identity of an identifier's value; equal keys mean the same entity."""
    text = span.text
    if span.type == "EMAIL":
        return ("EMAIL", text.casefold())
    if span.type == "PHONE":
        return ("PHONE", span.value or re.sub(r"\D", "", text))
    if span.type == "IBAN":
        return ("IBAN", re.sub(r"\s", "", text).upper())
    if span.type == "CUSTOMER_ID":
        return ("CUSTOMER_ID", re.sub(r"\D", "", text))
    if span.type == "IP_ADDRESS":
        return ("IP", text)
    if span.type == "ADDRESS":
        return ("ADDRESS", re.sub(r"[^a-z0-9]", "", strip_diacritics(transliterate(text))))
    key = mention_name_key(span) if span.type in ("PERSON", "ORGANIZATION") else None
    if key and key.is_full:
        return ("NAME", key.first or "", key.surname or "")
    return None  # DATE_OF_BIRTH and partial names are not unique to one person


class _Index:
    """Lookup helpers over the mention list."""

    def __init__(self, mentions: list[Span], docs: list[Document]) -> None:
        self.mentions = mentions
        self.docs = {doc.doc_id: doc for doc in docs}
        self.by_doc: dict[str, list[int]] = defaultdict(list)
        self.by_record: dict[str, list[int]] = defaultdict(list)
        for index, span in enumerate(mentions):
            self.by_doc[span.doc_id].append(index)
            self.by_record[self.docs[span.doc_id].record].append(index)

    def within(self, doc_id: str, start: int, end: int) -> list[int]:
        return [
            i for i in self.by_doc.get(doc_id, []) if start <= self.mentions[i].start and self.mentions[i].end <= end
        ]

    def overlapping(self, doc_id: str, start: int, end: int) -> list[int]:
        return [i for i in self.by_doc.get(doc_id, []) if self.mentions[i].start < end and start < self.mentions[i].end]

    def record_of(self, index: int) -> str:
        return self.docs[self.mentions[index].doc_id].record


def _is_name(idx: _Index, index: int) -> bool:
    return idx.mentions[index].type in ("PERSON", "ORGANIZATION")


def _link_equal_values(idx: _Index, clusters: Clusters) -> None:
    groups: dict[tuple[str, ...], list[int]] = defaultdict(list)
    for index, span in enumerate(idx.mentions):
        key = _value_key(span)
        if key:
            groups[key].append(index)
    for key in sorted(groups):
        first, *others = groups[key]
        for other in others:
            clusters.union(first, other)


def _link_structured_records(idx: _Index, clusters: Clusters) -> None:
    """Cells of one CSV row describe one party; free-text notes join them
    unless the notes mention a different person."""
    for record, members in idx.by_record.items():
        if record.split(":")[0] not in CSV_FILES:
            continue
        cells = [i for i in members if not idx.docs[idx.mentions[i].doc_id].is_free_text]
        notes = [i for i in members if idx.docs[idx.mentions[i].doc_id].is_free_text]
        cell_keys = [k for i in cells for k in clusters.keys[clusters.find(i)]]
        note_keys = [mention_name_key(idx.mentions[i]) for i in notes if idx.mentions[i].type == "PERSON"]
        notes_about_row = all(compatible(a, b) for a in note_keys if a for b in cell_keys)
        group = cells + (notes if notes_about_row else [])
        for other in group[1:]:
            clusters.union(group[0], other)


def _free_text_docs(idx: _Index) -> list[Document]:
    return [doc for doc_id, doc in idx.docs.items() if doc.is_free_text and doc_id in idx.by_doc]


def _link_header_pairs(idx: _Index, clusters: Clusters) -> None:
    for doc in _free_text_docs(idx):
        for name_rng, email_rng, _address in layout.name_email_pairs(doc.text):
            names = idx.overlapping(doc.doc_id, *name_rng)
            emails = idx.overlapping(doc.doc_id, *email_rng)
            for a in names:
                for b in emails:
                    clusters.union(a, b)


def _link_signature_blocks(idx: _Index, clusters: Clusters) -> None:
    for doc in _free_text_docs(idx):
        for start, end in layout.signature_blocks(doc.text):
            members = idx.within(doc.doc_id, start, end)
            names = [i for i in members if _is_name(idx, i)]
            if not names:
                continue
            for other in members:
                if other != names[0]:
                    clusters.union(names[0], other)


def _message_author(idx: _Index, doc: Document) -> tuple[int, int] | None:
    """(signer's mention index, signature start) of the newest message, if signed."""
    top_end = layout.top_message_end(doc.text)
    for start, end in layout.signature_blocks(doc.text):
        if start >= top_end:
            break
        names = [i for i in idx.within(doc.doc_id, start, end) if _is_name(idx, i)]
        return (names[0], start) if names else None
    return None


def _link_author_sentences(idx: _Index, clusters: Clusters) -> None:
    """In the newest message of a ticket or e-mail, identifiers in first-person
    sentences belong to the person who signed it. Sentences that also name a
    different person are skipped ("call my colleague Mr Varga on ...")."""
    for doc in _free_text_docs(idx):
        if doc.record.startswith(CHATS_FILE):
            continue  # chats are handled per handle
        found = _message_author(idx, doc)
        if found is None:
            continue
        author, signature_start = found
        author_keys = clusters.keys[clusters.find(author)]
        for start, end in layout.sentence_ranges(doc.text, 0, signature_start):
            if not layout.is_first_person(doc.text[start:end]):
                continue
            members = idx.within(doc.doc_id, start, end)
            names = [mention_name_key(idx.mentions[i]) for i in members if _is_name(idx, i)]
            if any(key and not all(compatible(key, a) for a in author_keys) for key in names):
                continue  # the sentence is about someone else too
            for other in members:
                if not _is_name(idx, other):
                    clusters.union(author, other)


def _link_chat_handles(idx: _Index, clusters: Clusters) -> None:
    """Identifiers typed by one chat handle belong to the same person."""
    by_handle: dict[tuple[str, str], list[int]] = defaultdict(list)
    anchors: dict[tuple[str, str], int] = {}
    for doc in idx.docs.values():
        if not doc.record.startswith(CHATS_FILE) or doc.field != "text":
            continue
        handle_doc = idx.docs.get(doc.doc_id[: -len("text")] + "handle")
        if handle_doc is None:
            continue
        key = (doc.record, handle_doc.text)
        members = idx.by_doc.get(doc.doc_id, [])
        by_handle[key].extend(i for i in members if not _is_name(idx, i))
        for start, end in layout.self_intro_ranges(doc.text, include_here=True):
            for i in idx.overlapping(doc.doc_id, start, end):
                if idx.mentions[i].type == "PERSON" and key not in anchors:
                    anchors[key] = i
    for key in sorted(by_handle):
        members = by_handle[key]
        if key in anchors:
            members = [anchors[key]] + members
        for other in members[1:]:
            clusters.union(members[0], other)


def _candidates(key: NameKey, roots: set[int], clusters: Clusters, own_root: int) -> list[int]:
    return sorted(
        root
        for root in roots
        if root != own_root and any(matches(key, anchor) for anchor in clusters.anchors.get(root, []))
    )


def _link_partial(index: int, key: NameKey, idx: _Index, clusters: Clusters) -> None:
    """Join a mention to the only full name it can refer to, if there is one."""
    own_root = clusters.find(index)
    record_roots = {clusters.find(i) for i in idx.by_record[idx.record_of(index)]}
    found = _candidates(key, record_roots, clusters, own_root)
    if not found:
        all_roots = {clusters.find(i) for i in range(len(idx.mentions))}
        found = _candidates(key, all_roots, clusters, own_root)
    if len(found) == 1:
        clusters.union(index, found[0])


def _link_name_keys(idx: _Index, clusters: Clusters) -> None:
    emails, specific, given_only = [], [], []
    for index, span in enumerate(idx.mentions):
        key = mention_name_key(span)
        if key is None:
            continue
        if span.type == "EMAIL":
            emails.append((index, key))
        elif not key.is_full:
            (specific if key.surname or key.word else given_only).append((index, key))
    for group in (emails, specific, given_only):
        for index, key in group:
            if clusters.anchors.get(clusters.find(index)):
                continue  # already attached to a full name
            _link_partial(index, key, idx, clusters)


def resolve(spans: list[Span], docs: list[Document]) -> list[Span]:
    """Return `spans` with `entity_id` set to a cluster label for PII mentions.

    Labels are E1, E2, ... in order of first appearance; non-PII spans keep
    an empty entity_id. Input order is preserved.
    """
    mention_positions = [pos for pos, span in enumerate(spans) if span.is_pii]
    mentions = [spans[pos] for pos in mention_positions]
    idx = _Index(mentions, docs)
    clusters = Clusters(mentions)
    _link_equal_values(idx, clusters)
    _link_structured_records(idx, clusters)
    _link_header_pairs(idx, clusters)
    _link_signature_blocks(idx, clusters)
    _link_author_sentences(idx, clusters)
    _link_chat_handles(idx, clusters)
    _link_name_keys(idx, clusters)

    labels: dict[int, str] = {}
    result = list(spans)
    for pos, index in zip(mention_positions, range(len(mentions))):
        root = clusters.find(index)
        labels.setdefault(root, f"E{len(labels) + 1}")
        result[pos] = replace(spans[pos], entity_id=labels[root])
    return result
