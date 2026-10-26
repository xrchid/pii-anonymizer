# piianon

Rule-based detection, linking and pseudonymization of personal data in business records:
CRM exports, support tickets, e-mail threads, chat logs and invoices.

The task it models is the one a human reviewer does before such records are shared or reused:

1. find personal data and give it a type (PERSON, EMAIL, PHONE, ADDRESS, DATE_OF_BIRTH, IBAN, IP_ADDRESS, CUSTOMER_ID, ORGANIZATION);
2. leave non-personal data alone: company names, `info@` and `support@` mailboxes, order and invoice numbers, version strings, amounts, ticket dates;
3. group mentions of the same person (`Oleksandr Kovalenko`, `Олександр Коваленко`, `Sasha`, `O. Kovalenko`, `o.kovalenko@…`, his phone in three formats) so they are replaced consistently;
4. measure all of this against gold annotations written by the data generator (offsets verified by tests) and list what went wrong.

Runtime uses only the Python 3.10+ standard library. Tests use `unittest`.

```text
Best regards,                              Best regards,
Ing. Peter Novák                           Ing. [PERSON_4]
Finance, Tatra Logistics s.r.o.            Finance, Tatra Logistics s.r.o.
(0908) 164-752                             [PHONE_4]

----- Forwarded message -----              ----- Forwarded message -----
From: Alexander Kovalenko <o.kovalenko@…>  From: [PERSON_1] <[EMAIL_1]>

Peťo, approved, … reach me on my private   [PERSON_4], approved, … reach me on my private
number 0905013389 until Friday.            number [PHONE_1] until Friday.

– Sasha                                    – [PERSON_1]
```

"Peťo" is linked to Peter Novák, "Alexander Kovalenko" and "Sasha" to the CRM record of Oleksandr Kovalenko, and the
phone written as `0905013389` to the same person's `+421 905 013 389`. The company name stays.

## How to run

```sh
python -m piianon generate --seed 42 --out data     # synthetic dataset + gold.jsonl + decoys.jsonl
python -m piianon detect --data data --out out/predictions.jsonl
python -m piianon anonymize --data data --predictions out/predictions.jsonl --out out/anonymized
python -m piianon evaluate --data data --predictions out/predictions.jsonl --json out/metrics.json
python -m piianon report --data data --predictions out/predictions.jsonl --out out/error_report.md
python -m unittest discover -s tests
```

`anonymize`, `evaluate` and `report` run detection in memory when `--predictions` is omitted. The dataset generated with
seed 42 is committed in `data/`, and the report from the run below is in [`docs/error_report.md`](docs/error_report.md).

## Labelling a new dataset

For a dataset in the same five-file format that has no `gold.jsonl`:

```sh
python -m piianon export-labeling --data new_data --out labels     # optionally: --prefill out/predictions.jsonl
# edit the files in labels/, then:
python -m piianon import-labels --data new_data --labels labels --out new_data/gold.jsonl
python -m piianon evaluate --data new_data                          # decoys.jsonl is optional
```

`export-labeling` writes `crm_export.txt`, `invoices.txt`, `tickets.txt`, `chats.txt` and `emails/thread_XX.txt`.
Each document is a block: a header line `### <doc_id>`, then the exact document text. Empty fields are left out,
because they cannot contain personal data. Mark personal data inline as `[[exact text|TYPE|ENTITY_ID]]`, for example
`[[Emily Carter|PERSON|P1]]` and `[[emily.carter@x.example|EMAIL|P1]]`. Use one entity id for every mention of a person.
A label may span lines, for example an address written over two lines. Change nothing else.

`import-labels` removes the markup and checks that what is left equals the original document character by character.
It then computes offsets and writes `gold.jsonl` with `is_pii=true`. It reports every problem as `file:line: message`
and writes nothing if there is a problem. Problems include an unknown type, an unclosed or nested label, an invalid
entity id, text changed outside a label, and a missing or duplicated block.

`--prefill` writes the system's predictions as labels, so the reviewer confirms, corrects or deletes them instead of
starting from nothing. The reviewer is then likely to accept what the system proposed, so do not use prefilled
labels to measure the system that produced them.

## Design

```text
piianon/
  synth.py      synthetic records + gold annotations (exact offsets, checked by reloading the files)
  dataset.py    every text field of the five file kinds as one Document; rewrites files field by field
  detect.py     rule-based detectors, two passes, overlap resolution, company-record rule
  layout.py     signature blocks, "Name <address>" headers, reply lines, sentences, self-introductions
  lexicon.py    first names and nicknames, titles, closings, role mailboxes, transliteration table
  resolve.py    normalization, name keys, union-find clustering with a cannot-link check
  anonymize.py  per-cluster placeholders, pseudonym key file
  evaluate.py   span P/R/F1, decoy false positives, B-cubed, markdown error report
  labeling.py   export documents for hand-labelling, import inline labels as gold.jsonl
```

[`docs/WALKTHROUGH.md`](docs/WALKTHROUGH.md) explains the data flow, the design decisions and the metrics in more detail.

**Documents.** Each CSV cell, each JSON string value and each e-mail file is a document with an id such as
`crm_export.csv:3:notes` or `chats.jsonl:2:messages.4.text`. Gold offsets, predictions and replacements all refer to
these ids, so the anonymized files keep the original structure.

**Detection** (`detect.py`; every detector's docstring says what it catches and what it ignores):

| Type | Rule | Deliberately ignored |
|---|---|---|
| EMAIL | regex; role local parts (`info`, `support`, `billing`, …) are returned with `is_pii=False` | obfuscated `name [at] domain` |
| PHONE | candidate regex, then E.164 normalization: needs `+`, `00` or trunk `0`; per-country digit counts | digit runs without a prefix (order numbers, amounts, years) |
| IBAN | country length + ISO 7064 mod-97 check; trailing words are cut | VAT IDs, bad checksums |
| IP_ADDRESS | IPv4 with octets 0–255 | dotted quads after `version`, `build`, `v`, `release` |
| DATE_OF_BIRTH | numeric and month-name dates (EN/SK/UK), only right after a birth word (`born`, `nar.`, `дата народження`) | all other dates |
| CUSTOMER_ID | `C-12345`, or five digits after `customer number` / `zákaznícke číslo` | `ORD-…`, `INV-…`, `T-…`, product codes |
| PERSON | gazetteer given name or nickname + capitalized words; words after a title, greeting, closing, `Name <address>`, `I'm …`; second pass: learned surnames, `O. Surname` | lower-case and all-caps names, stop words (`Customer`, `Support Team`), role-mailbox display names |
| ADDRESS | Slovak street (`-ova`, `-ská`, `-ná`, `-ého`, `trieda`) + number [+ postcode + city, also across a line break]; UK street types + postcode; Ukrainian `вул.` | a city or postcode alone, `version 12`, `Room 4` |
| ORGANIZATION | legal form (`s.r.o.`, `a.s.`, `Ltd`, `LLC`, `ТОВ «…»`) → not personal; sole traders (`FOP …`, `ФОП …`, `Full Name – trade`) → personal | company names without a legal form, unless seen with one elsewhere |

The first pass learns surnames from full names and company names from legal-form matches. The second pass uses them
to find `Mr Kovalenko`, `O. Kovalenko` and `Martin Precision` (a company whose name starts with a first name).
Overlapping candidates are reduced by a fixed priority (column hint, then type, then length). Two dataset-level rules
mark data as non-personal: the IBAN and billing address in an invoice row whose client is a company with a legal form,
and the same values wherever else they appear.

**Resolution** (`resolve.py`). Names are compared after case folding, Ukrainian Cyrillic-to-Latin transliteration
(2010 national system) and removal of diacritics, so `Олександр Коваленко` and `Oleksandr Kovalenko` give the same
key. A nickname table maps `Sasha`, `Alex`, `Alexander` to `oleksandr`. Mentions are joined with union-find in this order:

1. equal values (E.164 phone, e-mail, IBAN, customer number, IP, address, full name);
2. cells of one CSV row (free-text notes too, unless they mention someone else);
3. `Name <address>` pairs;
4. signature blocks, and first-person sentences ("my date of birth is …") of the newest message → the signer;
5. identifiers typed by one chat handle, plus the name the handle introduced itself with;
6. e-mail local parts (`o.kovalenko`, `horvathova.jana`, `katka.bielikova`);
7. partial names (`O. Kovalenko`, `Kovalenko`, `Sasha`) join a full name only if exactly one candidate exists,
   first within the same record, then in the whole dataset.

Every union is refused when the two clusters contain incompatible names (different surnames, or different given
names). This is what keeps Oleksandr Kovalenko and Oleksandr Bondarenko apart, and a bare "Oleksandr" that could be
either stays unlinked.

**Pseudonymization** (`anonymize.py`). PII spans become `[TYPE_n]`, where `n` is the cluster number, so one person is
`[PERSON_1]`, `[EMAIL_1]`, `[PHONE_1]` in every file. Non-PII spans are not touched. The placeholder-to-value table is
written to `out/pseudonym_key.json`, outside the anonymized folder.

## Dataset

All names, companies and identifiers are invented. Domains use `.example`, IP addresses come from the RFC 5737
documentation ranges, UK mobiles from Ofcom's drama range (07700 900xxx), and IBANs have valid check digits with
fictional bank codes. Slovak and Ukrainian numbers are random digits.

15 people and 5 organizations appear in 12 CRM rows, 9 tickets, 6 e-mail threads, 6 chats and 9 invoices
(274 gold spans, 216 of them PII, plus 134 decoys). The templates are fixed; the seed changes identifiers, dates and
amounts. Hard cases include: name variants and nicknames, Cyrillic and Latin forms of one name, Slovak diacritics and
ASCII spellings, `last.first` e-mail local parts, phones in seven formats, addresses split over two lines, birth dates
with Slovak and Ukrainian month names, two people called Oleksandr, a Slovak sole trader (`Jana Horváthová – Účtovné
služby`) and a Ukrainian one (`ФОП Мельник Дмитро`) next to limited companies, a company named after a first name
(`Martin Precision s.r.o.`, located in the town of Martin), and a married couple sharing an address.

Annotation conventions: titles (`Mr`, `Ing.`, `pani`) are outside PERSON spans; a city alone is not annotated; company
names, IBANs, addresses and role mailboxes are annotated with `is_pii=false`; chat handles and VAT IDs are not
annotated (see "Not visible in the metrics" below).

## Results

Seed 42, `python -m piianon evaluate`:

| Type | Gold | Predicted | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| PERSON | 93 | 92 | 0.978 | 0.968 | 0.973 | 0.978 | 0.968 | 0.973 |
| EMAIL | 38 | 37 | 1.000 | 0.974 | 0.987 | 1.000 | 0.974 | 0.987 |
| PHONE | 30 | 30 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| ADDRESS | 11 | 11 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| DATE_OF_BIRTH | 6 | 6 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| IBAN | 8 | 8 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| IP_ADDRESS | 6 | 6 | 0.833 | 0.833 | 0.833 | 0.833 | 0.833 | 0.833 |
| CUSTOMER_ID | 16 | 16 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| ORGANIZATION (sole traders) | 8 | 8 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| **micro avg** | 216 | 214 | 0.986 | 0.977 | 0.981 | 0.986 | 0.977 | 0.981 |

Non-personal items wrongly tagged as PII: **3 of 192** (2 of 12 city cells, 1 of 10 version strings; 0 of 36 company
names, 0 of 12 role mailboxes, 0 of 6 company addresses, 0 of 4 company IBANs, 0 of 112 other decoys).

| Clustering (B-cubed over gold PII mentions) | Mentions | Precision | Recall | F1 |
|---|---:|---:|---:|---:|
| all mentions (missed = singleton) | 216 | 0.991 | 0.907 | 0.947 |
| detected mentions only | 211 | 0.991 | 0.948 | 0.969 |

15 gold entities, 23 predicted clusters.

**Read these numbers with care.** The rules and the dataset were written by the same person, and the evaluation is
in-sample: the hard cases were chosen first and the rules were then written to cover most of them. Seeds 1, 7, 42, 123
and 2026 give identical scores because only identifier values change between seeds. The numbers show which of the
listed cases are handled; they are not an estimate of accuracy on real records, where vocabulary, formats and
languages vary far more. The dataset is also small (216 PII spans), so one error moves a per-type score by several points.

## Error analysis

All examples are from [`docs/error_report.md`](docs/error_report.md).

**Missed PII (5).**

- `hi its dmytro` and `DMYTRO MELNYK like in my passport`: the name rules require capitalized words. Lower case is
  common in chat; all caps is common when people copy names from documents. Accepting them would make every word
  that matches the gazetteer a candidate, so this needs a different signal (e.g. matching against names already
  known for the record) rather than a looser pattern.
- `our IT guy Radim has the details`: "Radim" is not in the gazetteer and there is no cue (title, greeting, signature).
  The surname lexicon learned "Kučera" from his full name in the CRM and an e-mail header, but given names are not
  learned.
- `n.shevchuk [at] karpaty-food.example`: obfuscated e-mail, not handled by the regex.
- `2001:db8:4a::17`: there is no IPv6 detector.

**False positives (3).**

- `Martin` in the CRM `city` column (twice): Martin is a common Slovak first name and a Slovak town. A column-aware
  rule (never PERSON in `city`) or a small gazetteer of place names would fix this case.
- `we are on 10.2.3.4 everywhere`: a version number without a context word is a valid IPv4 address. Here only the
  text says otherwise; `10.x.x.x` is a private range, but private addresses can still identify a device or user.

**Clustering errors.** Precision is high because of the cannot-link check; most errors are splits.

- Inflected names: Ukrainian genitive `пана Коваленка`, vocative `Привіт, Олександре!`, Slovak instrumental
  `s pánom Vargom`. They are detected but normalize to `kovalenka`, `oleksandre`, `vargom`, which match no full name.
  Stripping case endings would fix these, but in both languages it also creates new false links, so it was left out.
- `taking over the LedgerLite admin role from Oleksandr`: three people can be called Oleksandr/Alexander in the
  dataset, so the bare name is not linked. A reviewer would see that the writer and Kovalenko work for the same company.
- `Для перевірки: дата народження 16 листопада 1978, …`: the birth date in Dmytro Melnyk's Ukrainian e-mail is not
  linked to him. The author rule looks for first-person pronouns, and Ukrainian often marks the person only on the
  verb (`Прошу`).
- Shared address: Marek Bielik's invoice uses the same billing address as his wife Katarína Bieliková. Equal-value
  linking runs before record linking, so the address went into her cluster, and the cannot-link check then kept it
  away from Marek. The two people stay separate, but both invoices show `[ADDRESS_12]`. Greedy union-find is
  order-dependent; a scoring step that compares all evidence before linking would avoid this.

**Not visible in the metrics.**

- National Ukrainian phone numbers (`050 276 48 35`) are normalized as Slovak (`+421…`), because a leading 0 is
  assumed to be Slovak. Detection is still correct and signature/author rules linked them here, but value-based
  linking with the `+380` form fails.
- A sole trader's VAT ID identifies a person but is not in the type set; it stays in the output. Chat handles
  (`guest_4821`) are online identifiers and are not annotated either.
- One person with two e-mail addresses gets `[EMAIL_1]` for both, so the output no longer shows they were different.

## Privacy concepts

**Personal data.** GDPR Art. 4(1): "any information relating to an identified or identifiable natural person", where
identifiable means identifiable "directly or indirectly", for example by a name, an identification number, location
data or an online identifier.

**Direct, indirect and quasi-identifiers.** A direct identifier points to one person by itself: a name, a personal
e-mail address, a phone number, an IBAN, a customer number. Indirect identifiers do not, but they narrow the group:
date of birth, postcode, employer, job title. When a few of them are combined they often single out one person, which
is why they are called quasi-identifiers. Sweeney (2000) estimated that 87% of the US population was uniquely
identified by 5-digit ZIP code, gender and date of birth. In this dataset "Chief accountant at Karpaty Food in Lviv"
identifies one person even after her name is removed, and the tool does not handle that.

**`info@company.com` versus `firstname.lastname@company.com`.** Information about a company is not personal data;
information about an identifiable employee is (see the ICO guide below). A role mailbox such as `info@` or
`support@` names a function of the company and is usually read by several people. An address built from a person's
name identifies that employee directly, even though it belongs to the company domain. The tool therefore keeps
`support@dunajsoft.example` and replaces `o.kovalenko@tatra-logistics.example`. The judgement depends on context: a
one-person company's `info@` address can identify its owner.

**Sole traders.** A sole trader is the business: the trade name usually contains the person's name
(`Jana Horváthová – Účtovné služby`, `ФОП Мельник Дмитро`), and the business's address, IBAN and VAT ID are hers or
his. These spans are ORGANIZATION with `is_pii=true` and share the person's cluster. A limited company
(`Tatra Logistics s.r.o.`) is a legal person; its name, address and IBAN are not personal data.

**Pseudonymization versus anonymization.** GDPR Art. 4(5) defines pseudonymisation as processing personal data so
that it "can no longer be attributed to a specific data subject without the use of additional information", provided
that information is kept separately and protected. This tool pseudonymizes: consistent placeholders plus a key file
that maps them back. Pseudonymized data is still personal data. Anonymous data, from which people can no longer be
identified by reasonably likely means, falls outside the GDPR (Recital 26). The output here should not be called
anonymous, even without the key: the detector misses some spans, and quasi-identifiers (job titles, companies,
towns, dates) are left in the text.

Sources:

- GDPR Art. 4, Definitions: <https://gdpr-info.eu/art-4-gdpr/>
- ICO, What is personal information: a guide: <https://ico.org.uk/for-organisations/uk-gdpr-guidance-and-resources/personal-information-what-is-it/what-is-personal-information-a-guide/>
- L. Sweeney, *Simple Demographics Often Identify People Uniquely*, Carnegie Mellon University, Data Privacy Working Paper 3, 2000.

## License

MIT, see [LICENSE](LICENSE).
