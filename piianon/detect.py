"""Rule-based PII detectors.

Each `find_*` function takes a text and returns typed `Span`s (with an empty
doc_id). `detect_dataset` runs all of them over every document in two passes:
the first pass collects surnames and organization names that were found with
high confidence, the second pass uses them to find shorter mentions
("Mr Kovalenko", "O. Kovalenko", "Martin Precision" without "s.r.o.").
Overlapping candidates are reduced to one span by a fixed priority.

The rules favour precision on identifiers with a checksum or a strict shape
(IBAN, e-mail) and rely on context words where a pattern alone is ambiguous
(dates of birth, IP addresses next to "version").
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from datetime import date

from . import layout, lexicon
from .dataset import Document
from .resolve import normalize_name, strip_diacritics, transliterate
from .spans import Span

# Higher wins when two candidate spans overlap.
TYPE_PRIORITY: dict[str, int] = {
    "EMAIL": 9,
    "IBAN": 8,
    "IP_ADDRESS": 7,
    "CUSTOMER_ID": 6,
    "DATE_OF_BIRTH": 5,
    "PHONE": 4,
    "ORGANIZATION": 3,
    "ADDRESS": 2,
    "PERSON": 1,
}

_WORD_RE = re.compile(r"[^\W\d_]+(?:['’\-][^\W\d_]+)*")


def _span(text: str, start: int, end: int, type_: str, source: str, is_pii: bool = True, value: str = "") -> Span:
    return Span("", start, end, text[start:end], type_, is_pii=is_pii, source=source, value=value)


@dataclass(frozen=True)
class Lexicon:
    """Names learned from confident matches in the first pass."""

    surnames: frozenset[str] = frozenset()  # normalized
    org_names: tuple[str, ...] = ()  # surface forms without legal suffix, longest first


EMPTY_LEXICON = Lexicon()  # first pass: nothing learned yet


# ---------------------------------------------------------------- e-mail

EMAIL_RE = re.compile(
    r"(?<![\w.+-])[A-Za-z0-9][A-Za-z0-9._%+-]*@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}(?![\w-])"
)


def is_role_mailbox(address: str) -> bool:
    """True for shared mailboxes such as info@, support@, billing@."""
    local = address.split("@", 1)[0].casefold()
    return local in lexicon.ROLE_LOCAL_PARTS


def find_emails(text: str) -> list[Span]:
    """E-mail addresses.

    Catches: plain addresses anywhere, including inside "Name <address>".
    Role mailboxes (info@, support@, billing@ ...) are returned with
    is_pii=False: they name a function of an organization, not a person.
    Ignores: obfuscated forms such as "name [at] example.com".
    """
    return [
        _span(text, m.start(), m.end(), "EMAIL", "email-regex", not is_role_mailbox(m.group()), m.group().casefold())
        for m in EMAIL_RE.finditer(text)
    ]


# ---------------------------------------------------------------- phone

PHONE_RE = re.compile(r"(?<![\w@+/.-])(?:\+|00)?(?:\(\d{1,5}\)|\d)(?:[ ./-]?(?:\(\d{1,5}\)|\d)){6,16}(?![\w@/-]|\.\d)")
# Allowed national significant number lengths per country calling code.
COUNTRY_LENGTHS: dict[str, tuple[int, int]] = {
    "421": (9, 9),  # Slovakia
    "420": (9, 9),  # Czechia
    "380": (9, 9),  # Ukraine
    "48": (9, 9),  # Poland
    "36": (8, 9),  # Hungary
    "43": (4, 13),  # Austria
    "49": (6, 13),  # Germany
    "44": (10, 10),  # United Kingdom
}
_PHONE_NEGATIVE_CONTEXT = re.compile(r"(?:order|invoice|ticket|iban|account|sku|ref|#)\W*$", re.IGNORECASE)


def normalize_phone(raw: str, default_country: str = "421") -> str | None:
    """Return the number in E.164 form ("+421905123456") or None if invalid.

    International numbers need "+" or "00". National numbers need the trunk
    prefix 0: 11 digits starting with 07 are read as UK mobiles, anything
    else as `default_country` (Slovakia). Numbers without + or 0 are rejected,
    which filters out order numbers, amounts and years.
    """
    stripped = raw.strip()
    digits = re.sub(r"\D", "", stripped)
    if stripped.startswith("+"):
        international = digits
    elif digits.startswith("00"):
        international = digits[2:]
    elif digits.startswith("0"):
        if len(digits) == 11 and digits.startswith("07"):
            international = "44" + digits[1:]
        else:
            international = default_country + digits[1:]
    else:
        return None
    for code, (low, high) in COUNTRY_LENGTHS.items():
        if international.startswith(code):
            national = len(international) - len(code)
            return "+" + international if low <= national <= high else None
    return None


def find_phones(text: str) -> list[Span]:
    """Phone numbers in international or national format.

    Catches: +421 905 123 456, 00421905123456, 0905123456, (0905) 123-456,
    0905/123 456, +44 7700 900461, +380 67 123 4567.
    Ignores: digit runs without "+", "00" or a leading 0 (order numbers,
    amounts), numbers right after words like "order" or "invoice", and
    digit counts that do not fit the country.
    """
    spans = []
    for match in PHONE_RE.finditer(text):
        if _PHONE_NEGATIVE_CONTEXT.search(text[max(0, match.start() - 15) : match.start()]):
            continue
        e164 = normalize_phone(match.group())
        if e164:
            spans.append(_span(text, match.start(), match.end(), "PHONE", "phone-regex", value=e164))
    return spans


# ---------------------------------------------------------------- IBAN

IBAN_CANDIDATE_RE = re.compile(r"\b[A-Z]{2}\d{2}(?: ?[A-Z0-9]{4}){2,7}(?: ?[A-Z0-9]{1,3})?\b")
IBAN_LENGTHS: dict[str, int] = {"SK": 24, "CZ": 24, "UA": 29, "GB": 22, "DE": 22, "AT": 20, "PL": 28, "HU": 28}


def iban_is_valid(iban: str) -> bool:
    """ISO 13616 check: known country length and mod-97 remainder of 1."""
    compact = re.sub(r"\s", "", iban).upper()
    if len(compact) != IBAN_LENGTHS.get(compact[:2], -1) or not compact.isalnum():
        return False
    rearranged = compact[4:] + compact[:4]
    numeric = "".join(str(int(char, 36)) for char in rearranged)  # A=10 ... Z=35
    return int(numeric) % 97 == 1


def _iban_end(text: str, start: int, end: int) -> int | None:
    """Cut a candidate after the country's IBAN length (drops trailing words)."""
    expected = IBAN_LENGTHS.get(text[start : start + 2])
    if expected is None:
        return None
    count = 0
    for pos in range(start, end):
        if text[pos] != " ":
            count += 1
        if count == expected:
            stop = pos + 1
            if stop < len(text) and text[stop].isalnum():
                return None
            return stop
    return None


def find_ibans(text: str) -> list[Span]:
    """IBANs, spaced in groups of four or compact.

    Catches: SK31 1200 0000 1987 4263 7541, UA213223130000026007233566001.
    Ignores: strings whose length does not match the country or whose
    mod-97 checksum fails (VAT IDs such as SK1023456789, typos).
    """
    spans = []
    for match in IBAN_CANDIDATE_RE.finditer(text):
        end = _iban_end(text, match.start(), match.end())
        if end and iban_is_valid(text[match.start() : end]):
            compact = re.sub(r"\s", "", text[match.start() : end])
            spans.append(_span(text, match.start(), end, "IBAN", "iban-mod97", value=compact))
    return spans


# ---------------------------------------------------------------- IPv4

IPV4_RE = re.compile(r"(?<![\w.])(?:\d{1,3}\.){3}\d{1,3}(?![\w]|\.\d)")
VERSION_CONTEXT_RE = re.compile(r"(?:\bversion|\bver\.?|\bbuild|\brelease|\bfirmware|\bfw|\bv)\s*$", re.IGNORECASE)


def _valid_octets(candidate: str) -> bool:
    parts = candidate.split(".")
    return all(int(part) <= 255 and (part == "0" or not part.startswith("0")) for part in parts)


def find_ipv4(text: str) -> list[Span]:
    """IPv4 addresses.

    Catches: dotted quads with octets 0-255 and no leading zeros.
    Ignores: quads right after "version", "build", "release", "v" etc.
    ("version 10.2.3.4"), and anything with an octet over 255.
    """
    spans = []
    for match in IPV4_RE.finditer(text):
        before = text[max(0, match.start() - 20) : match.start()]
        if _valid_octets(match.group()) and not VERSION_CONTEXT_RE.search(before):
            spans.append(_span(text, match.start(), match.end(), "IP_ADDRESS", "ipv4"))
    return spans


# ---------------------------------------------------------------- date of birth

_MONTH_NAMES = "|".join(sorted(map(re.escape, lexicon.MONTHS), key=len, reverse=True))
DATE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\b(?P<d>\d{1,2})\.\s?(?P<m>\d{1,2})\.\s?(?P<y>\d{4})\b"),
    re.compile(r"\b(?P<d>\d{1,2})/(?P<m>\d{1,2})/(?P<y>\d{4})\b"),
    re.compile(r"\b(?P<y>\d{4})-(?P<m>\d{2})-(?P<d>\d{2})\b"),
    re.compile(rf"\b(?P<d>\d{{1,2}})\.?\s(?P<mname>{_MONTH_NAMES})\s(?P<y>\d{{4}})\b", re.IGNORECASE),
)
DOB_CONTEXT_RE = re.compile(
    r"(?:\bborn|date of birth|birth date|birthday|\bd\.o\.b\.|\bdob|narodený|narodená|narodenia|"
    r"\bnar\.|народився|народилася|народження)(?:\s+(?:on|is|was|je))?\s*[:\-–]?\s*$",
    re.IGNORECASE,
)


def _parse_date(match: re.Match[str]) -> date | None:
    groups = match.groupdict()
    month = lexicon.MONTHS[groups["mname"].casefold()] if groups.get("mname") else int(groups["m"])
    try:
        return date(int(groups["y"]), month, int(groups["d"]))
    except ValueError:
        return None


def find_dates_of_birth(text: str) -> list[Span]:
    """Dates of birth, only when a birth context word directly precedes them.

    Catches: "Born 12.04.1988", "date of birth is 1988-04-12",
    "nar. 3. mája 1985", "дата народження 7 листопада 1990".
    Ignores: every other date (ticket timestamps, invoice and reply dates),
    impossible dates, and years outside 1900-2015.
    """
    spans = []
    for pattern in DATE_PATTERNS:
        for match in pattern.finditer(text):
            parsed = _parse_date(match)
            if parsed is None or not 1900 <= parsed.year <= 2015:
                continue
            if DOB_CONTEXT_RE.search(text[max(0, match.start() - 40) : match.start()]):
                spans.append(
                    _span(text, match.start(), match.end(), "DATE_OF_BIRTH", "dob-context", value=parsed.isoformat())
                )
    return spans


# ---------------------------------------------------------------- customer IDs

CUSTOMER_ID_RE = re.compile(r"\bC-\d{5}\b")
CUSTOMER_NUMBER_RE = re.compile(
    r"(?:customer\s+(?:number|no\.?|id|#)|cust\.\s*no\.?|zákaznícke\s+číslo|číslo\s+zákazníka|номер\s+клієнта)"
    r"\s*:?\s*(?:is\s+)?(?P<num>\d{5})\b",
    re.IGNORECASE,
)


def find_customer_ids(text: str) -> list[Span]:
    """Customer numbers of the CRM.

    Catches: "C-10042" anywhere, and a bare 5-digit number right after
    "customer number", "cust. no." or "zákaznícke číslo".
    Ignores: order, invoice, ticket and product codes (ORD-..., INV-...,
    T-..., BX-...), which have different prefixes.
    """
    spans = [_span(text, m.start(), m.end(), "CUSTOMER_ID", "customer-id") for m in CUSTOMER_ID_RE.finditer(text)]
    for match in CUSTOMER_NUMBER_RE.finditer(text):
        spans.append(_span(text, match.start("num"), match.end("num"), "CUSTOMER_ID", "customer-number-context"))
    return spans


# ---------------------------------------------------------------- organizations

LEGAL_SUFFIX_RE = re.compile(
    r"(?<=\s)(?:s\.\s?r\.\s?o\.|spol\.\s?s\s?r\.\s?o\.|a\.\s?s\.|Ltd\.?|Limited|LLC|Inc\.?|GmbH|plc|Corp\.?)(?!\w)"
)
UA_ORG_RE = re.compile(r"(?<!\w)(?:ТОВ|ТзОВ|ПП|ПрАТ|АТ)\s?«[^»\n]{1,60}»")
FOP_RE = re.compile(r"(?<!\w)(?:ФОП|FOP)[ \t]+(?P<name>[^\W\d_]+(?:[ \t][^\W\d_]+){1,2})")
SOLE_TRADER_TAIL_RE = re.compile(r"[ \t]+[–-][ \t]+(?P<trade>[^\W\d_][^\n,.;:|()<>]{1,40})")


def _org_name_start(text: str, suffix_start: int, max_words: int = 4) -> int | None:
    """Walk left from a legal suffix over capitalized words on the same line."""
    line_start = text.rfind("\n", 0, suffix_start) + 1
    words = list(_WORD_RE.finditer(text, line_start, suffix_start))
    start = None
    pos = suffix_start
    for word in reversed(words[-max_words:]):
        gap = text[word.end() : pos]
        if gap not in (" ", " & ") or not (layout.is_capitalized(word.group()) or word.group().isupper()):
            break
        start = word.start()
        pos = word.start()
    return start


def find_organizations(text: str) -> list[Span]:
    """Company names with a legal form, and sole traders.

    Catches: "Tatra Logistics s.r.o.", "Brightwell Components Ltd",
    "ТОВ «Карпати Фуд»" (is_pii=False: a legal person's name is not personal
    data), and Ukrainian sole traders "FOP Dmytro Melnyk" / "ФОП Мельник
    Дмитро" (is_pii=True: the trade name is the person's name).
    Slovak sole-trader names ("Jana Horváthová – Účtovné služby") are found
    by `find_sole_traders`, which needs the person spans first.
    Ignores: company names without a legal form (see the org lexicon).
    """
    spans = []
    for match in LEGAL_SUFFIX_RE.finditer(text):
        start = _org_name_start(text, match.start())
        if start is not None:
            spans.append(_span(text, start, match.end(), "ORGANIZATION", "legal-suffix", is_pii=False))
    for match in UA_ORG_RE.finditer(text):
        spans.append(_span(text, match.start(), match.end(), "ORGANIZATION", "legal-prefix", is_pii=False))
    for match in FOP_RE.finditer(text):
        words = [w for w in _WORD_RE.finditer(text, *match.span("name"))]
        kept = []
        for word in words:
            if not layout.is_capitalized(word.group()):
                break
            kept.append(word)
        if len(kept) >= 2:
            spans.append(_span(text, match.start(), kept[-1].end(), "ORGANIZATION", "sole-trader-fop"))
    return spans


def find_sole_traders(text: str, persons: list[Span]) -> list[Span]:
    """Slovak-style sole-trader names: a full personal name, a dash, a trade.

    "Jana Horváthová – Účtovné služby" is a business name that contains a
    natural person's name, so it is personal data. A dash followed by a job
    title ("Lucia Benková – Customer Success") is not treated as a trade name.
    """
    spans = []
    for person in persons:
        if len(_WORD_RE.findall(person.text)) < 2:
            continue
        match = SOLE_TRADER_TAIL_RE.match(text, person.end)
        if not match:
            continue
        trade = match.group("trade").rstrip()
        trade_words = {normalize_name(w) for w in _WORD_RE.findall(trade)}
        if trade_words & lexicon.JOB_TITLE_WORDS:
            continue
        end = match.start("trade") + len(trade)
        spans.append(_span(text, person.start, end, "ORGANIZATION", "sole-trader-dash"))
    return spans


def find_known_organizations(text: str, lex: Lexicon) -> list[Span]:
    """Second-pass: company names seen elsewhere with a legal form, written
    here without it ("Martin Precision" next to "Martin Precision s.r.o.")."""
    spans = []
    for name in lex.org_names:
        for match in re.finditer(rf"(?<!\w){re.escape(name)}(?!\w)", text):
            spans.append(_span(text, match.start(), match.end(), "ORGANIZATION", "org-lexicon", is_pii=False))
    return spans


# ---------------------------------------------------------------- person names


@dataclass(frozen=True)
class _Token:
    start: int
    end: int
    text: str
    norm: str


def _tokens(text: str) -> list[_Token]:
    return [_Token(m.start(), m.end(), m.group(), normalize_name(m.group())) for m in _WORD_RE.finditer(text)]


def _is_name_word(token: _Token) -> bool:
    return (
        layout.is_capitalized(token.text) and token.norm not in lexicon.STOPWORDS and token.norm not in lexicon.TITLES
    )


def _extend_name(text: str, tokens: list[_Token], first: int, max_extra: int = 2) -> int:
    """Index of the last token of a name starting at tokens[first]."""
    last = first
    while (
        last + 1 < len(tokens)
        and last - first < max_extra
        and text[tokens[last].end : tokens[last + 1].start] == " "
        and _is_name_word(tokens[last + 1])
    ):
        last += 1
    return last


def _gazetteer_names(text: str, tokens: list[_Token]) -> list[Span]:
    """A known given name or nickname, plus up to two capitalized words."""
    spans = []
    for i, token in enumerate(tokens):
        if layout.is_capitalized(token.text) and token.norm in lexicon.FIRST_NAMES:
            last = _extend_name(text, tokens, i)
            source = "gazetteer-full" if last > i else "gazetteer-first"
            spans.append(_span(text, token.start, tokens[last].end, "PERSON", source))
    return spans


def _title_names(text: str, tokens: list[_Token]) -> list[Span]:
    """Words after an honorific: "Mr Kovalenko", "pani Benková", "пана Коваленка"."""
    spans = []
    for i, token in enumerate(tokens[:-1]):
        if token.norm not in lexicon.TITLES:
            continue
        gap = text[token.end : tokens[i + 1].start]
        if gap not in (" ", ". ") or not _is_name_word(tokens[i + 1]):
            continue
        last = _extend_name(text, tokens, i + 1, max_extra=1)
        spans.append(_span(text, tokens[i + 1].start, tokens[last].end, "PERSON", "title"))
    return spans


def _lexicon_names(text: str, tokens: list[_Token], lex: Lexicon) -> list[Span]:
    """Known surnames alone ("Kovalenko") or after an initial ("O. Kovalenko")."""
    spans = []
    for i, token in enumerate(tokens):
        if not (_is_name_word(token) and token.norm in lex.surnames):
            continue
        start = token.start
        if i > 0:
            prev = tokens[i - 1]
            if len(prev.text) == 1 and prev.text.isupper() and text[prev.end : token.start] in (". ", "."):
                start = prev.start
        spans.append(_span(text, start, token.end, "PERSON", "surname-lexicon"))
    return spans


GREETING_RE = re.compile(
    r"(?:%s)(?![^\W\d_])[ \t,]+" % "|".join(re.escape(g) for g in sorted(lexicon.GREETINGS, key=len, reverse=True)),
    re.IGNORECASE,
)


def _greeting_names(text: str) -> list[Span]:
    """The addressee after a greeting at the start of a line ("Hi Tomáš,")."""
    spans = []
    for line in layout.split_lines(text):
        match = GREETING_RE.match(line.content)
        if not match:
            continue
        pos = line.content_start + match.end()
        words = list(_WORD_RE.finditer(text, pos, line.end))
        if words and words[0].start() == pos and normalize_name(words[0].group()) in lexicon.TITLES:
            words = words[1:]
            pos = words[0].start() if words else pos
        kept = []
        for word in words:
            gap_ok = word.start() == pos if not kept else text[kept[-1].end() : word.start()] == " "
            token = _Token(word.start(), word.end(), word.group(), normalize_name(word.group()))
            if not gap_ok or not _is_name_word(token) or len(kept) == 2:
                break
            kept.append(word)
        if kept:
            spans.append(_span(text, kept[0].start(), kept[-1].end(), "PERSON", "greeting"))
    return spans


def _layout_names(text: str) -> list[Span]:
    """Names in signatures, e-mail headers, reply lines and self-introductions."""
    spans = [_span(text, s, e, "PERSON", "signature") for s, e in layout.signature_name_ranges(text)]
    for (start, end), _email_rng, address in layout.name_email_pairs(text):
        rng = layout.name_like_range(text, start, end)
        if rng and not is_role_mailbox(address):
            spans.append(_span(text, *rng, "PERSON", "header"))
    for start, end in layout.wrote_line_names(text):
        rng = layout.name_like_range(text, start, end)
        if rng:
            spans.append(_span(text, *rng, "PERSON", "reply-header"))
    for start, end in layout.self_intro_ranges(text):
        spans.append(_span(text, start, end, "PERSON", "self-intro"))
    return spans


def find_person_names(text: str, lex: Lexicon = EMPTY_LEXICON) -> list[Span]:
    """Names of natural persons.

    Catches: a gazetteer given name or nickname (English, Slovak, Ukrainian
    in Latin or Cyrillic) plus following capitalized words; capitalized words
    after a title, a greeting, a closing ("Best regards,") or in "Name
    <address>"; and, in the second pass, surnames learned in the first pass,
    alone or after an initial.
    Ignores: lower-case names ("its dmytro"), inflected forms not in the
    lists (Ukrainian vocative "Олександре" is only found after a greeting),
    stop words such as "Customer" or "Support Team", and display names of
    role mailboxes ("Dunaj Support <support@...>").
    """
    tokens = _tokens(text)
    spans = _gazetteer_names(text, tokens) + _title_names(text, tokens)
    spans += _greeting_names(text) + _layout_names(text)
    if lex.surnames:
        spans += _lexicon_names(text, tokens, lex)
    return spans


# ---------------------------------------------------------------- addresses

HOUSE_NUMBER_RE = re.compile(r"(?<= )\d{1,4}[a-zA-Z]?(?:/\d{1,4}[a-zA-Z]?|/[A-Z])?(?![\w/])")
SK_STREET_ENDINGS: tuple[str, ...] = ("ova", "ová", "ská", "ná", "cká", "ého")
STREET_TYPE_WORDS: frozenset[str] = frozenset({"trieda", "cesta", "námestie", "nábrežie", "ulica", "nám."})
SK_POSTAL_TAIL_RE = re.compile(
    r"(?:,[ \t]*|[ \t]*\n[ \t>]*)(?P<zip>\d{3} ?\d{2})[ \t]+(?P<city>[^\W\d_]+(?:[ \t][^\W\d_]+)?)"
)
UK_STREET_RE = re.compile(
    r"(?:(?:Unit|Flat|Suite|Apartment)\s\d{1,4}[A-Z]?,\s)?(?:\d{1,4}[A-Z]?\s)?[A-Z][a-z]+(?:\s[A-Z][a-z]+)?\s"
    r"(?:Street|St|Road|Rd|Lane|Ln|Avenue|Ave|Grove|Close|Drive|Way|Place|Park|Crescent|Terrace|Gardens)\b"
)
UK_POSTCODE_TAIL_RE = re.compile(r",\s(?P<city>[A-Z][a-z]+(?:\s[A-Z][a-z]+)?)\s[A-Z]{1,2}\d[A-Z\d]?\s?\d[A-Z]{2}\b")
UA_STREET_RE = re.compile(
    r"(?<!\w)(?:вул\.|вулиця|просп\.|пров\.|пл\.|vul\.|prosp\.)\s?[^\W\d_][\w'’\-]*(?:\s[^\W\d_][\w'’\-]*)?,?\s\d{1,4}[а-яa-z]?(?!\w)"
)
UA_TAIL_RES: tuple[re.Pattern[str], ...] = (
    re.compile(r",\s?(?:кв\.|kv\.)\s?\d{1,4}"),
    re.compile(r",\s?(?P<city>[^\W\d_]+)"),
    re.compile(r",\s?\d{5}(?!\d)"),
)


def _is_street_word(word: str) -> bool:
    return layout.is_capitalized(word) and word.casefold().endswith(SK_STREET_ENDINGS)


def _sk_street_start(text: str, number_start: int) -> int | None:
    """Start of a Slovak street name ending right before a house number."""
    line_start = text.rfind("\n", 0, number_start) + 1
    words = list(_WORD_RE.finditer(text, line_start, number_start))
    if not words or text[words[-1].end() : number_start] != " ":
        return None
    last = words[-1]
    if _is_street_word(last.group()):
        start = last.start()
    elif last.group().casefold() in STREET_TYPE_WORDS and len(words) >= 2 and layout.is_capitalized(words[-2].group()):
        if text[words[-2].end() : last.start()] != " ":
            return None
        start = words[-2].start()
    else:
        return None
    prefix = text[max(line_start, start - 5) : start]
    for marker in ("ul. ", "nám. "):
        if prefix.endswith(marker):
            start -= len(marker)
    return start


def _postal_tail_end(text: str, end: int) -> int:
    match = SK_POSTAL_TAIL_RE.match(text, end)
    if not match:
        return end
    city_words = match.group("city").split()
    kept = [w for w in city_words[:1] if layout.is_capitalized(w)]
    if len(city_words) > 1 and kept and layout.is_capitalized(city_words[1]):
        kept.append(city_words[1])
    if not kept:
        return end
    return match.start("city") + len(" ".join(kept))


def find_addresses(text: str) -> list[Span]:
    """Postal addresses (street + house number, optionally postcode and city).

    Catches: Slovak streets ending in -ova/-ská/-ná/-ého or with "trieda",
    "cesta" ("Hlavná 12, 040 01 Košice", also split over two lines), UK
    "27 Elm Grove, Leeds LS6 2AB" / "Unit 4, Riverside Park, Leeds LS11 5QT",
    Ukrainian "вул. Шевченка, 15, Львів, 79000".
    Ignores: a city or postcode on its own, and "word + number" pairs that do
    not look like a street ("version 12", "Windows 11", "Room 4").
    """
    spans = []
    for match in HOUSE_NUMBER_RE.finditer(text):
        start = _sk_street_start(text, match.start())
        if start is not None:
            end = _postal_tail_end(text, match.end())
            spans.append(_span(text, start, end, "ADDRESS", "street-sk"))
    for match in UK_STREET_RE.finditer(text):
        tail = UK_POSTCODE_TAIL_RE.match(text, match.end())
        has_number = bool(re.search(r"\d", match.group()))
        if tail or has_number:
            spans.append(_span(text, match.start(), tail.end() if tail else match.end(), "ADDRESS", "street-uk"))
    for match in UA_STREET_RE.finditer(text):
        end = match.end()
        for tail_re in UA_TAIL_RES:
            tail = tail_re.match(text, end)
            if tail and (not tail.groupdict().get("city") or layout.is_capitalized(tail.group("city"))):
                end = tail.end()
        spans.append(_span(text, match.start(), end, "ADDRESS", "street-ua"))
    return spans


# ---------------------------------------------------------------- column hints

PARTY_FIELDS: frozenset[str] = frozenset({"company", "client_name"})


def classify_party_name(value: str) -> tuple[str, bool]:
    """(type, is_pii) for a value in a "company"/"client" column.

    Legal form -> non-personal organization; "FOP ..." or "Full Name – trade"
    -> sole trader (personal); anything else -> treated as a person's name.
    """
    if any(_span_covers_end(s, value) for s in find_organizations(value) if not s.is_pii) or UA_ORG_RE.fullmatch(value):
        return "ORGANIZATION", False
    if FOP_RE.match(value):
        return "ORGANIZATION", True
    persons = [s for s in find_person_names(value) if s.start == 0]
    if persons and find_sole_traders(value, persons):
        return "ORGANIZATION", True
    return "PERSON", True


def _span_covers_end(span: Span, value: str) -> bool:
    return span.end == len(value.rstrip())


def find_column_hints(doc: Document) -> list[Span]:
    """Whole-cell spans for columns whose meaning is known.

    full_name -> PERSON, billing_address -> ADDRESS, company/client_name ->
    see `classify_party_name`. (A company column without a legal form is
    still an organization; a client column without one is a person.)
    """
    value = doc.text.strip()
    if not value:
        return []
    start = doc.text.index(value)
    end = start + len(value)
    if doc.field == "full_name":
        return [_span(doc.text, start, end, "PERSON", "column")]
    if doc.field == "billing_address":
        return [_span(doc.text, start, end, "ADDRESS", "column")]
    if doc.field in PARTY_FIELDS:
        type_, is_pii = classify_party_name(value)
        if doc.field == "company" and type_ == "PERSON":
            type_, is_pii = "ORGANIZATION", False
        return [_span(doc.text, start, end, type_, "column", is_pii=is_pii)]
    return []


# ---------------------------------------------------------------- combining


def select_spans(candidates: list[Span]) -> list[Span]:
    """Keep a non-overlapping subset: column hints first, then type priority,
    then the longer span, then the earlier one."""
    ranked = sorted(
        candidates,
        key=lambda s: (s.source != "column", -TYPE_PRIORITY[s.type], -s.length, s.start, s.source),
    )
    chosen: list[Span] = []
    for span in ranked:
        if all(span.end <= kept.start or kept.end <= span.start for kept in chosen):
            chosen.append(span)
    return sorted(chosen, key=lambda s: s.start)


def detect_text(text: str, lex: Lexicon = EMPTY_LEXICON) -> list[Span]:
    """Run every free-text detector on one text."""
    persons = find_person_names(text, lex)
    candidates = (
        find_emails(text)
        + find_phones(text)
        + find_ibans(text)
        + find_ipv4(text)
        + find_dates_of_birth(text)
        + find_customer_ids(text)
        + find_organizations(text)
        + find_sole_traders(text, persons)
        + find_known_organizations(text, lex)
        + find_addresses(text)
        + persons
    )
    return select_spans(candidates)


def detect_document(doc: Document, lex: Lexicon = EMPTY_LEXICON) -> list[Span]:
    spans = select_spans(find_column_hints(doc) + detect_text(doc.text, lex))
    return [replace(span, doc_id=doc.doc_id) for span in spans]


def _surname_of(name: str) -> str | None:
    words = [normalize_name(w) for w in _WORD_RE.findall(name)]
    words = [w for w in words if w and w not in lexicon.TITLES and w != "fop"]
    if len(words) < 2:
        return None
    if words[0] in lexicon.FIRST_NAMES:
        return words[-1]
    if words[-1] in lexicon.FIRST_NAMES:
        return words[0]
    return words[-1]


def build_lexicon(spans: list[Span]) -> Lexicon:
    """Collect surnames of full names and names of companies with a legal form."""
    org_names = set()
    for span in spans:
        if span.type == "ORGANIZATION" and not span.is_pii and span.source in ("legal-suffix", "column"):
            match = LEGAL_SUFFIX_RE.search(span.text)
            if match:
                org_names.add(span.text[: match.start()].rstrip())
    org_norms = {normalize_name(name) for name in org_names}
    surnames = set()
    for span in spans:
        if span.type == "PERSON" or (span.type == "ORGANIZATION" and span.is_pii):
            person_part = re.split(r"\s[–-]\s", span.text)[0]
            norm = normalize_name(person_part)
            if any(org.startswith(norm) or norm.startswith(org) for org in org_norms):
                continue  # "Martin Precision" is a company, not a person
            surname = _surname_of(person_part)
            if surname and surname not in lexicon.STOPWORDS:
                surnames.add(surname)
    return Lexicon(frozenset(surnames), tuple(sorted(org_names, key=lambda n: (-len(n), n))))


# Identifiers in a record whose party is a company describe the company.
COMPANY_OWNED_TYPES: frozenset[str] = frozenset({"IBAN", "ADDRESS"})


def _identity(span: Span) -> str:
    return re.sub(r"[^a-z0-9]", "", strip_diacritics(transliterate(span.text)))


def apply_company_record_rule(spans: list[Span], docs: list[Document]) -> list[Span]:
    """Mark IBANs and addresses of companies as non-personal.

    In an invoice row whose client is a company with a legal form, the IBAN
    and billing address belong to that company. The same values found in
    free text elsewhere are then also marked non-personal.
    """
    by_id = {doc.doc_id: doc for doc in docs}
    company_records = {
        by_id[s.doc_id].record
        for s in spans
        if s.type == "ORGANIZATION" and not s.is_pii and by_id[s.doc_id].field == "client_name"
    }
    company_values = {
        (s.type, _identity(s))
        for s in spans
        if s.type in COMPANY_OWNED_TYPES and by_id[s.doc_id].record in company_records
    }
    return [
        replace(s, is_pii=False, source=s.source + "+company-record")
        if s.type in COMPANY_OWNED_TYPES and (s.type, _identity(s)) in company_values
        else s
        for s in spans
    ]


def detect_dataset(docs: list[Document]) -> list[Span]:
    """Detect spans in every document (two passes, then record rules)."""
    first_pass = [span for doc in docs for span in detect_document(doc)]
    lex = build_lexicon(first_pass)
    spans = [span for doc in docs for span in detect_document(doc, lex)]
    return apply_company_record_rule(spans, docs)
