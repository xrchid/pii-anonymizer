# Design notes

How the data flows, what each module does, why it was built this way, how the metrics are calculated,
and where it fails.

## 1. The problem

A company wants to share or reuse its records (a CRM export, support tickets, e-mails, chat logs, invoices) without
exposing the people in them. Someone has to find every piece of personal data, give it a type, leave non-personal
data alone (company names, `info@` mailboxes, order numbers), and make sure that every mention of one person gets
the same replacement in every file. This project does those steps with transparent rules and measures how well it
does them against gold annotations.

## 2. Data flow

```text
data/ (five file kinds)
  │  dataset.load_documents        one Document per CSV cell, JSON string value, or e-mail file
  ▼
documents
  │  detect.detect_dataset         pass 1: all detectors → learn surnames + company names
  │                                pass 2: all detectors again, using what was learned
  │                                company-record rule: company IBANs/addresses → is_pii=False
  ▼
typed spans (doc_id, start, end, type, is_pii, source)
  │  resolve.resolve               union-find over PII spans → cluster label E1, E2, ...
  ▼
out/predictions.jsonl
  ├─ anonymize.anonymize_dataset → out/anonymized/ (same five file kinds) + out/pseudonym_key.json
  └─ evaluate.evaluate / error_report  compared with data/gold.jsonl (+ data/decoys.jsonl if present)

For a dataset without gold:
  labeling.export_labeling → label files → a person adds [[text|TYPE|ID]] → labeling.import_labels → gold.jsonl
```

One mention, end to end. In `data/emails/thread_03.txt` the forwarded message is signed `– Sasha`.

1. `load_documents` makes the whole e-mail file one document, `emails/thread_03.txt`.
2. `detect` finds `Sasha` because it is in the nickname list (`lexicon.NAME_GROUPS`, group `oleksandr`). The span is
   PERSON, source `gazetteer-first`.
3. `resolve` turns it into the name key `first=oleksandr`, with no surname. The same e-mail contains
   `Oleksandr Kovalenko <o.kovalenko@…>` in the Cc line, which is already in the cluster of the CRM row. That is the
   only full name in this record with the given name `oleksandr`, so `Sasha` joins that cluster.
4. `anonymize` writes `– [PERSON_1]`, with the same number as the CRM row, his e-mail, and his phone.

## 3. Modules

- **`spans.py`** – the `Span` and `Decoy` records that every stage passes around, and JSONL read/write helpers.
- **`dataset.py`** – turns the five file kinds into a flat list of `Document`s and back. A document id says where the
  text lives (`crm_export.csv:3:notes`, `chats.jsonl:2:messages.4.text`). `transform_files` rewrites every field
  through a function, which is how the anonymized copy keeps the original CSV columns and JSON structure.
- **`synth.py`** – writes the synthetic dataset from fixed templates. Tags such as `{P01:Sasha}` or
  `{P01.phone.paren}` are expanded while the text is built, so each gold span's offsets are known exactly. After
  writing, the files are reloaded and every span is checked against the text. The seed changes the identifiers,
  dates and amounts, not the templates.
- **`lexicon.py`** – the word lists: given names and nicknames, titles, stop words, closings, greetings, role
  mailbox names, month names, and the Ukrainian transliteration table.
- **`layout.py`** – finds the shape of a message without deciding what is a name: quoted lines, signature blocks,
  `Name <address>` pairs, `On … wrote:` lines, sentences, self-introductions (`I'm Lucia`, `Sasha here`).
- **`detect.py`** – one function per type (`find_emails`, `find_phones`, `find_ibans`, ...), each with a docstring
  saying what it catches and what it ignores. `select_spans` resolves overlaps, `detect_dataset` runs the two passes,
  and `apply_company_record_rule` marks company-owned IBANs and addresses as non-personal.
- **`resolve.py`** – normalizes names (case, transliteration, diacritics, nicknames) into `NameKey`s and links
  mentions in seven ordered steps. `Clusters` is a union-find that refuses a merge when two names conflict.
- **`anonymize.py`** – numbers clusters in order of first appearance and replaces each PII span with `[TYPE_n]`.
  It writes the key (placeholder → original values) to a separate file.
- **`evaluate.py`** – span precision/recall/F1 (exact and overlap), the non-personal table, B-cubed, and the
  markdown error report.
- **`labeling.py`** – exports documents as plain-text blocks for a person to label, and imports the labels as
  `gold.jsonl` after checking that only markup was added.
- **`__main__.py`** – the command line: `generate`, `detect`, `anonymize`, `evaluate`, `report`,
  `export-labeling`, `import-labels`.

## 4. Key design decisions and their trade-offs

1. **Rules instead of a trained model.** Each span records the rule that produced it, so every decision can be
   explained and fixed in one place. The rules need no training data and no dependencies, and identifiers with a
   strict shape (IBAN with a checksum, e-mail, E.164 phone) are handled better by rules than by statistics anyway.
   *Cost:* names and addresses outside the word lists and patterns are missed, and each new language means new
   lists. A named-entity model would generalize better on names, but it needs labelled data, is harder to audit,
   and still needs rules for checksums and context. In practice the two are combined.

2. **One document per field.** Each CSV cell, JSON value and e-mail is its own document. Offsets are then simple and
   exact, the files can be rewritten with the same structure, and a column name can be used as a hint
   (`full_name` → PERSON). *Cost:* a detector sees one cell at a time, so information across cells of a row is only
   used later, in resolution.

3. **Two detection passes.** Pass 1 finds confident full names and companies with a legal form; pass 2 uses those
   surnames and company names to find `Mr Kovalenko`, `O. Kovalenko` and `Martin Precision` (without `s.r.o.`).
   *Cost:* a mistake in pass 1 is repeated in pass 2.

4. **Context before pattern for ambiguous types.** A date is a date of birth only right after a birth word; a dotted
   quad after `version` is not an IP; a digit run is a phone only with `+`, `00` or a leading `0`. This trades recall
   for precision, which matters because most numbers in business records are not personal data.

5. **Overlaps resolved by a fixed priority** (column hint, then type priority, then length). This is simple and
   deterministic. *Cost:* no nested spans, so `Jana Horváthová` inside the sole-trader name
   `Jana Horváthová – Účtovné služby` is only part of the ORGANIZATION span.

6. **Annotation conventions.**
   - Titles (`Mr`, `Ing.`, `pani`) are outside PERSON spans.
   - A city on its own is not PII. It is a quasi-identifier, but tagging every town makes the output useless.
   - A company's IBAN, address and `info@` mailbox are not PII.
   - A sole trader's business name, IBAN and address are PII.
   - Chat handles and VAT IDs are not annotated, because they are not in the nine types.

   The GDPR protects natural persons, so information about a legal person is out of scope. The exact line matters
   less than applying it the same way everywhere, which is why it is written down.

7. **Union-find for grouping.** Linking is transitive (if A is B and B is C, then A is C), union-find does this in
   almost linear time, and it is easy to explain. *Cost:* it is greedy and order-dependent, and a merge cannot be
   undone. The shared-address error comes from this. A scoring approach (compare all evidence for a pair, then
   cluster) would avoid it but is harder to explain and tune.

8. **Refuse doubtful links.** A merge is refused if the names conflict. A partial name joins a full name only if
   exactly one candidate exists, first in the same record, then in the whole dataset. Wrongly merging two people
   corrupts the output and is hard to notice; a split only costs consistency. So the resolver prefers splits:
   B-cubed precision 0.991, recall 0.907.

9. **Pseudonymize per cluster, key stored separately.** `[PERSON_1]`, `[EMAIL_1]`, `[PHONE_1]` share a number, so
   analysts can still follow one customer across files. *Cost:* this is pseudonymization, not anonymization, and two
   different e-mail addresses of one person both become `[EMAIL_1]`.

10. **Evaluation built in.**
    - The generator writes gold annotations with verified offsets, and decoys are scored separately.
    - Clustering is scored with B-cubed.
    - An error report lists every miss with context.
    - For honest numbers there is a hand-labelling path for a dataset written by someone else.

    *Cost:* on the synthetic data the evaluation is in-sample (same author for rules and data), so its scores are
    optimistic.

11. **Standard library only.** Anyone with Python 3.10 can run and review it. *Cost:* Python's `re` has no Unicode
    property classes such as `\p{Lu}`, so capitalization is checked with `str.isupper()`. Some things a library would
    give for free, such as a phone number database, are reduced to a small table.

## 5. How the metrics work

**Span precision, recall, F1.** Only spans with `is_pii=true` are compared.

- *Exact match*: a predicted span counts as correct if a gold span has the same document, start, end and type.
- *Overlap match*: same document and type, at least one shared character. Precision = predicted spans that overlap a
  gold span / all predicted spans; recall = gold spans overlapped by a prediction / all gold spans.
- F1 = 2PR / (P + R). The micro average adds up the counts over all types before dividing, so frequent types weigh
  more.

Exact match is stricter. Overlap match tells you whether the right thing was found, even if the boundary differs
(`Ing. Peter Novák` vs `Peter Novák`). The gap between the two is the number of boundary errors; here it is zero.

*Example:* the gold set has 93 PERSON spans and the system predicts 92. 90 of the predictions match gold, so
P = 90/92 = 0.978. 90 gold spans are found, so R = 90/93 = 0.968, and F1 = 0.973.

**Non-personal table.** It covers every decoy and every gold span with `is_pii=false`. "Tagged as PII" counts those
that a PII prediction overlaps. This table answers "how often do we destroy data we should keep?", which recall
cannot show.

**B-cubed.** For each gold mention *m*, let *C* be the mentions in its predicted cluster and *G* the mentions of its
gold entity.

- precision(*m*) = |C ∩ G| / |C|
- recall(*m*) = |C ∩ G| / |G|

Average over all mentions, then F1. A mention the detector missed counts as its own cluster. *Example:* entity A has
mentions a1, a2, a3, and the system makes clusters {a1, a2} and {a3}. Precision is 1 for every mention. Recall is
2/3, 2/3 and 1/3, which averages to 0.556. B-cubed is per mention, so it punishes both merges and splits, and big
entities do not dominate the way they do in pairwise counts. It is a standard measure for coreference and entity
resolution.

## 6. Known limitations

- **Names** in lower case (`hi its dmytro`) or all capitals (`DMYTRO MELNYK`) are missed. Given names outside the
  list (`Radim`) are missed unless a cue such as a greeting or signature is present.
- **Inflected names** (`Коваленка`, `Олександре`, `Vargom`) are detected but not linked.
- **A bare first name** that fits several people (`Oleksandr`) stays unlinked.
- **Ukrainian sentences** often mark the person only on the verb, so the first-person rule misses them.
- **No IPv6.** Obfuscated e-mails (`name [at] domain`) are missed. A version number without a context word looks like
  an IP address.
- **National Ukrainian phone numbers** are normalized as Slovak.
- **`Martin`** (a first name and a Slovak town) in a city column is tagged as a person.
- **Shared addresses** are linked by value before records are linked, so one household's address can end up in the
  wrong person's cluster.
- **Quasi-identifiers stay in the text:** job titles, companies, towns and dates. The output is pseudonymized, not
  anonymous.
- **The scores are in-sample.** They were measured on synthetic data written alongside the rules.
