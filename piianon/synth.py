"""Deterministic synthetic dataset with gold PII annotations.

All people, companies and identifiers are invented. E-mail domains use the
reserved ``.example`` top-level domain, IP addresses come from the RFC 5737
documentation ranges, UK mobile numbers from Ofcom's drama range
(07700 900xxx), and IBANs have valid check digits but fictional bank codes.

The document templates are fixed, so every hard case appears for any seed;
the seed controls identifiers (phone digits, IBANs, birth dates, customer
numbers, house numbers, IPs), timestamps and amounts.

Templates mark annotated text with tags:

* ``{P01:Sasha}``            PERSON mention of entity P01 (ORGANIZATION for an org entity)
* ``{P03@org:Jana ... }``    sole-trader business name, ORGANIZATION with is_pii=True
* ``{P06!EMAIL:n.shevchuk [at] ...}``  explicit type for text with no generator
* ``{P01.phone.paren}``      an identifier of P01 rendered in a given format
* ``{~VERSION_STRING:10.2.3.4}``  a decoy: looks like PII but is not
"""

from __future__ import annotations

import random
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

from . import dataset
from .spans import Decoy, Span, write_jsonl

# ---------------------------------------------------------------- cast


@dataclass
class Entity:
    key: str
    is_person: bool
    emails: list[str] = field(default_factory=list)
    phone: tuple[str, tuple[str, ...]] | None = None  # (country code, national digit groups)
    dob: date | None = None
    iban: str | None = None  # compact
    ip: str | None = None
    cid: str | None = None  # five digits
    address: tuple[str, str] | None = None  # (street part, postcode + city part)


def make_iban(country: str, bban: str) -> str:
    """Compute ISO 13616 check digits for a country code and BBAN."""
    numeric = "".join(str(int(char, 36)) for char in bban + country + "00")
    check = 98 - int(numeric) % 97
    return f"{country}{check:02d}{bban}"


def _digits(rng: random.Random, count: int) -> str:
    return "".join(str(rng.randint(0, 9)) for _ in range(count))


def _sk_mobile(rng: random.Random) -> tuple[str, tuple[str, ...]]:
    return "421", (rng.choice(["905", "908", "915", "944", "948"]), _digits(rng, 3), _digits(rng, 3))


def _ua_mobile(rng: random.Random) -> tuple[str, tuple[str, ...]]:
    return "380", (rng.choice(["67", "50", "63", "97"]), _digits(rng, 3), _digits(rng, 2), _digits(rng, 2))


def _uk_drama_mobile(rng: random.Random) -> tuple[str, tuple[str, ...]]:
    return "44", ("7700", "900" + _digits(rng, 3))  # Ofcom range reserved for fiction


def _sk_iban(rng: random.Random) -> str:
    return make_iban("SK", rng.choice(["9901", "9902", "9903"]) + "000000" + _digits(rng, 10))


def _ua_iban(rng: random.Random) -> str:
    return make_iban("UA", "399999" + _digits(rng, 19))


def _gb_iban(rng: random.Random) -> str:
    return make_iban("GB", "ZZBK" + _digits(rng, 14))


def _dob(rng: random.Random) -> date:
    return date(rng.randint(1965, 2000), rng.randint(1, 12), rng.randint(1, 28))


def build_cast(rng: random.Random) -> dict[str, Entity]:
    """Fifteen people and five organizations with seeded identifiers."""
    cids = [str(n) for n in rng.sample(range(10000, 99999), 13)]

    def house() -> int:
        return rng.randint(2, 120)

    cast = [
        Entity(
            "P01",
            True,
            ["o.kovalenko@tatra-logistics.example", "sasha.k92@mail.example"],
            _sk_mobile(rng),
            _dob(rng),
            _sk_iban(rng),
            f"203.0.113.{rng.randint(2, 254)}",
            cids[0],
            (f"Moyzesova {house()}", "040 01 Košice"),
        ),
        Entity("P02", True, ["oleksandr.bondarenko@karpaty-food.example"], _ua_mobile(rng), cid=cids[1]),
        Entity(
            "P03",
            True,
            ["horvathova.jana@ucto-horvathova.example"],
            _sk_mobile(rng),
            iban=_sk_iban(rng),
            cid=cids[2],
            address=(f"Hlavná {house()}", "040 01 Košice"),
        ),
        Entity("P04", True, ["peter.novak@tatra-logistics.example"], _sk_mobile(rng), cid=cids[3]),
        Entity(
            "P05",
            True,
            ["l.stastny@martinprecision.example"],
            ("421", ("41", _digits(rng, 3), _digits(rng, 4))),
            cid=cids[4],
        ),
        Entity("P06", True, ["n.shevchuk@karpaty-food.example"], _ua_mobile(rng), _dob(rng), cid=cids[5]),
        Entity(
            "P07",
            True,
            ["dmytro.melnyk@mail.example"],
            _ua_mobile(rng),
            _dob(rng),
            _ua_iban(rng),
            f"198.51.100.{rng.randint(2, 254)}",
            cids[6],
            (f"вул. Шевченка, {house()}", "Львів, 79000"),
        ),
        Entity("P08", True, ["emily.carter@brightwell.example"], _uk_drama_mobile(rng), cid=cids[7]),
        Entity(
            "P09",
            True,
            ["a.wright@brightwell.example"],
            _uk_drama_mobile(rng),
            ip=f"192.0.2.{rng.randint(2, 254)}",
            cid=cids[8],
        ),
        Entity(
            "P10",
            True,
            ["katka.bielikova@mail.example"],
            _sk_mobile(rng),
            _dob(rng),
            _sk_iban(rng),
            cid=cids[9],
            address=(f"Štúrova {house()}/A", "811 02 Bratislava"),
        ),
        Entity("P11", True, ["lucia.benkova@dunajsoft.example"], ("421", ("2", _digits(rng, 4), _digits(rng, 4)))),
        Entity("P12", True, ["t.kollar@dunajsoft.example"]),
        Entity("P13", True, ["michal.varga@martinprecision.example"], _sk_mobile(rng), cid=cids[10]),
        Entity("P14", True, ["r.kucera@tatra-logistics.example"], _sk_mobile(rng), cid=cids[11]),
        Entity("P15", True, ["marek.bielik@mail.example"], iban=_sk_iban(rng)),
        Entity(
            "ORG1",
            False,
            ["info@tatra-logistics.example"],
            iban=_sk_iban(rng),
            address=(f"Južná trieda {house()}", "040 01 Košice"),
        ),
        Entity(
            "ORG2",
            False,
            ["accounts@brightwell.example"],
            iban=_gb_iban(rng),
            address=(f"Unit {rng.randint(2, 20)}, Riverside Park", "Leeds LS11 5QT"),
        ),
        Entity(
            "ORG3",
            False,
            ["info@karpaty-food.example", "billing@karpaty-food.example"],
            iban=_ua_iban(rng),
            address=(f"вул. Городоцька, {house()}", "Львів, 79022"),
        ),
        Entity(
            "ORG4",
            False,
            ["office@martinprecision.example"],
            iban=_sk_iban(rng),
            address=(f"Hollého {house()}", "036 01 Martin"),
        ),
        Entity("ORG5", False, ["support@dunajsoft.example", "billing@dunajsoft.example"]),
    ]
    by_key = {entity.key: entity for entity in cast}
    by_key["P15"].address = by_key["P10"].address  # Marek Bielik lives with Katarína Bieliková
    return by_key


# ---------------------------------------------------------------- formatting

EN_MONTHS = [
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
]
SK_MONTHS_GEN = [
    "januára",
    "februára",
    "marca",
    "apríla",
    "mája",
    "júna",
    "júla",
    "augusta",
    "septembra",
    "októbra",
    "novembra",
    "decembra",
]
UK_MONTHS_GEN = [
    "січня",
    "лютого",
    "березня",
    "квітня",
    "травня",
    "червня",
    "липня",
    "серпня",
    "вересня",
    "жовтня",
    "листопада",
    "грудня",
]


def format_phone(phone: tuple[str, tuple[str, ...]], style: str) -> str:
    code, groups = phone
    national, rest = "0" + groups[0], list(groups[1:])
    formats = {
        "intl": f"+{code} " + " ".join(groups),
        "compact": f"+{code}" + "".join(groups),
        "00": f"00{code} " + " ".join(groups),
        "national": " ".join([national] + rest),
        "plain": national + "".join(rest),
        "paren": f"({national}) {rest[0]}-{''.join(rest[1:])}",
        "slash": f"{national}/" + " ".join(rest),
    }
    return formats[style]


def format_dob(value: date, style: str) -> str:
    formats = {
        "dmy": f"{value.day:02d}.{value.month:02d}.{value.year}",
        "iso": value.isoformat(),
        "slash": f"{value.day:02d}/{value.month:02d}/{value.year}",
        "long_en": f"{value.day} {EN_MONTHS[value.month - 1]} {value.year}",
        "sk": f"{value.day}. {SK_MONTHS_GEN[value.month - 1]} {value.year}",
        "uk": f"{value.day} {UK_MONTHS_GEN[value.month - 1]} {value.year}",
    }
    return formats[style]


def format_iban(iban: str, style: str) -> str:
    if style == "compact":
        return iban
    return " ".join(iban[i : i + 4] for i in range(0, len(iban), 4))


def format_address(address: tuple[str, str], style: str) -> str:
    street, locality = address
    return {"line": f"{street}, {locality}", "lines": f"{street}\n{locality}", "street": street}[style]


# ---------------------------------------------------------------- template rendering


@dataclass
class Built:
    """Text of one field plus gold spans and decoys at exact offsets."""

    text: str
    spans: list[tuple[int, int, str, str, bool]]  # start, end, type, entity_id, is_pii
    decoys: list[tuple[int, int, str]]  # start, end, kind


_TAG_RE = re.compile(r"\{([^{}]+)\}")
_ATTRIBUTE_TYPES = {
    "email": "EMAIL",
    "email2": "EMAIL",
    "phone": "PHONE",
    "dob": "DATE_OF_BIRTH",
    "iban": "IBAN",
    "ip": "IP_ADDRESS",
    "cid": "CUSTOMER_ID",
    "addr": "ADDRESS",
}
_DEFAULT_STYLE = {"phone": "intl", "dob": "dmy", "iban": "spaced", "addr": "line", "cid": "prefixed"}


def _attribute_text(entity: Entity, attribute: str, style: str) -> str:
    if attribute in ("email", "email2"):
        return entity.emails[0 if attribute == "email" else 1]
    if attribute == "phone" and entity.phone:
        return format_phone(entity.phone, style)
    if attribute == "dob" and entity.dob:
        return format_dob(entity.dob, style)
    if attribute == "iban" and entity.iban:
        return format_iban(entity.iban, style)
    if attribute == "ip" and entity.ip:
        return entity.ip
    if attribute == "cid" and entity.cid:
        return entity.cid if style == "num" else f"C-{entity.cid}"
    if attribute == "addr" and entity.address:
        return format_address(entity.address, style)
    raise KeyError(f"{entity.key} has no {attribute}")


def render(template: str, cast: dict[str, Entity]) -> Built:
    """Expand tags in `template`, recording each tagged piece of text."""
    parts: list[str] = []
    spans: list[tuple[int, int, str, str, bool]] = []
    decoys: list[tuple[int, int, str]] = []
    length = 0

    def emit(piece: str) -> tuple[int, int]:
        nonlocal length
        parts.append(piece)
        length += len(piece)
        return length - len(piece), length

    position = 0
    for match in _TAG_RE.finditer(template):
        emit(template[position : match.start()])
        tag = match.group(1)
        if tag.startswith("~"):
            kind, _, value = tag[1:].partition(":")
            start, end = emit(value)
            decoys.append((start, end, kind))
        elif ":" in tag:
            ref, _, surface = tag.partition(":")
            ref, _, explicit_type = ref.partition("!")
            sole_trader = ref.endswith("@org")
            entity = cast[ref.removesuffix("@org")]
            start, end = emit(surface)
            if explicit_type:
                spans.append((start, end, explicit_type, entity.key, entity.is_person))
            elif sole_trader:
                spans.append((start, end, "ORGANIZATION", entity.key, True))
            else:
                type_ = "PERSON" if entity.is_person else "ORGANIZATION"
                spans.append((start, end, type_, entity.key, entity.is_person))
        else:
            key, attribute, *style = tag.split(".")
            entity = cast[key]
            text = _attribute_text(entity, attribute, style[0] if style else _DEFAULT_STYLE.get(attribute, ""))
            start, end = emit(text)
            spans.append((start, end, _ATTRIBUTE_TYPES[attribute], entity.key, entity.is_person))
        position = match.end()
    emit(template[position:])
    return Built("".join(parts), spans, decoys)


def plain(text: str) -> Built:
    return Built(text, [], [])


def decoy(text: str, kind: str) -> Built:
    return Built(text, [], [(0, len(text), kind)])


# ---------------------------------------------------------------- documents

CRM_HEADER = ["customer_id", "full_name", "email", "phone", "company", "city", "notes"]
CRM_ROWS: list[tuple[str, ...]] = [
    (
        "{P01.cid}",
        "{P01:Oleksandr Kovalenko}",
        "{P01.email}",
        "{P01.phone.intl}",
        "{ORG1:Tatra Logistics s.r.o.}",
        "Košice",
        "Operations manager. Prefers calls after 14:00 on {P01.phone.paren}. Born {P01.dob.dmy}. "
        "Asked about the upgrade to version {~VERSION_STRING:10.2.3.4}.",
    ),
    (
        "{P02.cid}",
        "{P02:Oleksandr Bondarenko}",
        "{P02.email}",
        "{P02.phone.compact}",
        "{ORG3:Karpaty Food LLC}",
        "Lviv",
        "Not the same person as {P01:Oleksandr Kovalenko} at Tatra. Ordered 5 seats of LedgerLite "
        "({~ORDER_NUMBER:ORD-2026-11873}).",
    ),
    (
        "{P03.cid}",
        "{P03:Jana Horváthová}",
        "{P03.email}",
        "{P03.phone.plain}",
        "{P03@org:Jana Horváthová – Účtovné služby}",
        "Košice",
        "Sole trader. Invoices to {P03.addr.line}. Pays by transfer from {P03.iban.spaced}.",
    ),
    (
        "{P04.cid}",
        "{P04:Peter Novák}",
        "{P04.email}",
        "{P04.phone.paren}",
        "{ORG1:Tatra Logistics s.r.o.}",
        "Košice",
        "Finance contact; wants invoices copied to {ORG1.email}. Colleagues call him {P04:Peťo}.",
    ),
    (
        "{P05.cid}",
        "{P05:Ľubomír Šťastný}",
        "{P05.email}",
        "{P05.phone.intl}",
        "{ORG4:Martin Precision s.r.o.}",
        "Martin",
        "CEO. Deputy: {P13:Michal Varga}. Licence key for {~PRODUCT_CODE:BX-4410-22} sent on {~MESSAGE_DATE:02.03.2026}.",
    ),
    (
        "{P06.cid}",
        "{P06:Наталія Шевчук}",
        "{P06.email}",
        "{P06.phone.intl}",
        "{ORG3:ТОВ «Карпати Фуд»}",
        "Lviv",
        "Chief accountant. Writes her name as {P06:Nataliia} in Latin; colleagues use {P06:Natalia}. "
        "Date of birth {P06.dob.long_en} (identity check).",
    ),
    (
        "{P07.cid}",
        "{P07:Dmytro Melnyk}",
        "{P07.email}",
        "{P07.phone.national}",
        "{P07@org:FOP Dmytro Melnyk}",
        "Lviv",
        "Ukrainian sole trader. Last login from {P07.ip}.",
    ),
    (
        "{P08.cid}",
        "{P08:Emily Carter}",
        "{P08.email}",
        "{P08.phone.intl}",
        "{ORG2:Brightwell Components Ltd}",
        "Leeds",
        "UK office, call {P08.phone.national}; one hour behind CET.",
    ),
    (
        "{P09.cid}",
        "{P09:Alexander Wright}",
        "{P09.email}",
        "{P09.phone.intl}",
        "{ORG2:Brightwell Components Ltd}",
        "Leeds",
        "Goes by {P09:Alex}. Signs the renewals.",
    ),
    (
        "{P10.cid}",
        "{P10:Katarína Bieliková}",
        "{P10.email}",
        "{P10.phone.plain}",
        "",
        "Bratislava",
        "Private customer. Dátum narodenia: {P10.dob.dmy}. Lives at {P10.addr.line}.",
    ),
    (
        "{P13.cid}",
        "{P13:Michal Varga}",
        "{P13.email}",
        "{P13.phone.slash}",
        "{ORG4:Martin Precision s.r.o.}",
        "Martin",
        "Reachable via the {ORG4:Martin Precision} reception; prefers e-mail.",
    ),
    (
        "{P14.cid}",
        "{P14:Radim Kučera}",
        "{P14.email}",
        "{P14.phone.00}",
        "{ORG1:Tatra Logistics s.r.o.}",
        "Košice",
        "IT admin, took over the LedgerLite admin role from {P01:O. Kovalenko} in March.",
    ),
]

TICKETS: list[tuple[str, str]] = [
    (
        "Export fails after update to version {~VERSION_STRING:10.2.3.4}",
        "Hello {P11:Lucia},\n\n"
        "since the update to version {~VERSION_STRING:10.2.3.4} the CSV export stops at 80 %. I tried from the "
        "office and from home (IP {P01.ip}). Our customer number is {P01.cid}.\n\n"
        "Best regards,\n{P01:Oleksandr Kovalenko}\nOperations Manager, {ORG1:Tatra Logistics s.r.o.}\n"
        "M: {P01.phone.intl}\n\n"
        "On {~MESSAGE_DATE:12.03.2026} {P11:Lucia Benková} wrote:\n"
        "> Dear Mr {P01:Kovalenko},\n> could you tell us which version you are running?\n"
        "> Kind regards,\n> {P11:Lucia Benková}\n> {ORG5:Dunaj Software a.s.} | {ORG5.email}\n",
    ),
    (
        "Cannot log in",
        "Hi,\n\nI can't log in since yesterday. My account e-mail is {P10.email} and my date of birth is "
        "{P10.dob.dmy} if you need to verify me. I also moved to {P10.addr.line} last month. Please create a login for my husband "
        "{P15:Marek} too ({P15.email}).\n\n"
        "Thanks,\n{P10:Katka}\n",
    ),
    (
        "Missing invoice {~INVOICE_NUMBER:INV-2026-0042}",
        "Добрий день!\n\nWe did not receive invoice {~INVOICE_NUMBER:INV-2026-0042} for March. Please send it to "
        "{P06.email}, not to {ORG3.email}.\n\n"
        "З повагою,\n{P06:Наталія Шевчук}\nГоловний бухгалтер, {ORG3:ТОВ «Карпати Фуд»}\nтел. {P06.phone.intl}\n",
    ),
    (
        "Oprava faktúry {~INVOICE_NUMBER:INV-2026-0039}",
        "Dobrý deň, pani {P11:Benková},\n\nprosím o opravu faktúry {~INVOICE_NUMBER:INV-2026-0039}. Faktúra má "
        "byť vystavená na {P03@org:Jana Horváthová – Účtovné služby}, fakturačná adresa {P03.addr.line}. "
        "Preplatok prosím vráťte na účet {P03.iban.spaced}.\n\n"
        "S pozdravom\n{P03:Jana Horváthová}\n{P03.phone.national}\n",
    ),
    (
        "Licence server rejects activation",
        "Hello,\n\nthe licence server at our plant (build {~VERSION_STRING:4.12.0.1}) rejects the key for "
        "{~PRODUCT_CODE:BX-4410-22}. If I am not available, please contact my colleague Mr {P13:Varga} on "
        "{P13.phone.intl}.\n\n"
        "Regards,\n{P05:Lubomir Stastny}\nCEO, {ORG4:Martin Precision s.r.o.}\n{P05.email} | {P05.phone.intl}\n",
    ),
    (
        "API requests blocked",
        "Hi {P12:Tomáš},\n\n{P09:Alex} here from {ORG2:Brightwell}. Since Monday our API calls are rejected; the "
        "requests come from {P09.ip} and {P09!IP_ADDRESS:2001:db8:4a::17}. Could you whitelist them?\n\n"
        "Cheers,\n{P09:Alex Wright}\n{ORG2:Brightwell Components Ltd}\n{P09.phone.intl}\n",
    ),
    (
        "Change payer on invoice {~INVOICE_NUMBER:INV-2026-0046}",
        "Hello,\n\nI am a sole trader ({P07@org:ФОП Мельник Дмитро}). Please change the payer on invoice "
        "{~INVOICE_NUMBER:INV-2026-0046} to {P07@org:FOP Dmytro Melnyk}, IBAN {P07.iban.spaced}.\n\n"
        "Thanks, {P07:Dima}\n",
    ),
    (
        "Additional seats",
        "Dear support,\n\nI am writing on behalf of {ORG3:Karpaty Food LLC}. We need 5 more seats "
        "({~ORDER_NUMBER:ORD-2026-11902}). Please send the invoice to our accounting at {ORG3.email2}.\n\n"
        "Kind regards,\n{P02:Oleksandr Bondarenko}\n{ORG3:Karpaty Food LLC}\n{P02.phone.national}\n\n"
        "-----Original Message-----\nFrom: {P12:Tomáš Kollár} <{P12.email}>\nSent: {~MESSAGE_DATE:05.03.2026}\n"
        "> Dear {~SALUTATION:Customer},\n> your seats were extended. Order {~ORDER_NUMBER:ORD-2026-11873} is closed.\n"
        "> Best,\n> {P12:Tomas Kollar}\n",
    ),
    (
        "Feature request",
        "Dear {~SALUTATION:Support Team},\n\nplease add an export to XLSX in version {~VERSION_STRING:10.3.0.1}. "
        "Our admin mailbox is {ORG4.email}.\n\nRegards,\n{ORG4:Martin Precision} IT\n",
    ),
]

EMAILS: list[str] = [
    # thread_01: renewal with Brightwell; role mailbox display name; company billing address
    "From: {P08:Emily Carter} <{P08.email}>\n"
    "To: {~ROLE_DISPLAY_NAME:Dunaj Support} <{ORG5.email}>\n"
    "Cc: {P09:Alexander Wright} <{P09.email}>\n"
    "Date: Tue, {~MESSAGE_DATE:10 Mar 2026} 10:21:00 +0000\n"
    "Subject: Re: Renewal quote for {ORG2:Brightwell Components Ltd}\n\n"
    "Hi {P11:Lucia},\n\n"
    "thanks for the quote. {P09:Alex} will sign it on our side, so please send the contract to him directly. "
    "Our billing address is {ORG2.addr.line}.\n\n"
    "Best,\n{P08:Emily Carter}\nProcurement Lead | {ORG2:Brightwell Components Ltd}\n{P08.phone.intl}\n\n"
    "-----Original Message-----\n"
    "From: {P11:Lucia Benková} <{P11.email}>\n"
    "Sent: {~MESSAGE_DATE:09 March 2026} 16:02\n"
    "To: {P08:Emily Carter} <{P08.email}>\n"
    "Subject: Renewal quote for {ORG2:Brightwell Components Ltd}\n\n"
    "Dear Ms {P08:Carter},\n\n"
    "please find the renewal quote attached (customer {P08.cid}). The total is {~AMOUNT:4 860.00 GBP}.\n\n"
    "Kind regards,\n{P11:Lucia Benková}\nCustomer Success, {ORG5:Dunaj Software a.s.}\n{P11.phone.intl}\n",
    # thread_02: Ukrainian internal mail; vocative and genitive name forms; national UA phone format
    "From: {P06:Наталія Шевчук} <{P06.email}>\n"
    "To: {P02:Oleksandr Bondarenko} <{P02.email}>\n"
    "Cc: {ORG5.email2}\n"
    "Date: Wed, {~MESSAGE_DATE:11 Mar 2026} 08:05:00 +0200\n"
    "Subject: Рахунок {~INVOICE_NUMBER:INV-2026-0042}\n\n"
    "Привіт, {P02:Олександре}!\n\n"
    "Пересилаю рахунок від {ORG5:Dunaj Software a.s.}. Будь ласка, підтвердь, що замовлення "
    "{~ORDER_NUMBER:ORD-2026-11873} закрите. Якщо будуть питання, телефонуй мені: {P06.phone.national}.\n\n"
    "Також передай копію для пана {P01:Коваленка} з {ORG1:Tatra Logistics}.\n\n"
    "З повагою,\n{P06:Наталія}\n",
    # thread_03: forwarded approval; nicknames Peťo/Sasha, English name variant, same phone in another format
    "From: {P04:Peter Novák} <{P04.email}>\n"
    "To: {ORG5.email2}\n"
    "Cc: {ORG1.email}, {P01:Oleksandr Kovalenko} <{P01.email}>\n"
    "Date: Thu, {~MESSAGE_DATE:12 Mar 2026} 13:40:00 +0100\n"
    "Subject: FW: Approval for invoice {~INVOICE_NUMBER:INV-2026-0040}\n\n"
    "Hello,\n\nforwarding the approval from our operations manager. Please register it under my customer "
    "number {P04.cid.num}.\n\n"
    "Best regards,\nIng. {P04:Peter Novák}\nFinance, {ORG1:Tatra Logistics s.r.o.}\n{P04.phone.paren}\n\n"
    "----- Forwarded message -----\n"
    "From: {P01:Alexander Kovalenko} <{P01.email}>\n"
    "Date: {~MESSAGE_DATE:12.03.2026}\n\n"
    "{P04:Peťo}, approved, please forward it to billing. I am travelling, so reach me on my private number "
    "{P01.phone.plain} until Friday.\n\n– {P01:Sasha}\n",
    # thread_04: Slovak; ASCII spelling of names; company address in free text
    "From: {P05:Ľubomír Šťastný} <{P05.email}>\n"
    "To: {P12:Tomáš Kollár} <{P12.email}>\n"
    "Date: Fri, {~MESSAGE_DATE:13 Mar 2026} 09:15:00 +0100\n"
    "Subject: Re: Aktivácia licencie\n\n"
    "Dobrý deň, pán {P12:Kollár},\n\n"
    "ďakujem, aktivácia už funguje. Pre fakturáciu prosím použite adresu {ORG4.addr.line}. "
    "Kontakt na kolegu: {P13:Michal Varga}, {P13.email}. Termín školenia som dohodol s pánom {P13:Vargom}.\n\n"
    "S pozdravom\n{P05:Ľubomír Šťastný}\n{ORG4:Martin Precision s.r.o.}\n\n"
    "On {~MESSAGE_DATE:12.03.2026} 17:20, {P12:Tomas Kollar} <{P12.email}> wrote:\n"
    "> Dear Mr {P05:Stastny},\n> please try the activation again with version {~VERSION_STRING:4.12.0.2}.\n"
    "> Best regards,\n> {P12:Tomas Kollar}\n> {ORG5:Dunaj Software a.s.}\n",
    # thread_05: Ukrainian identity check; Cyrillic name, birth date with month name, address, IP
    "From: {P07:Дмитро Мельник} <{P07.email}>\n"
    "To: {~ROLE_DISPLAY_NAME:Dunaj Software Support} <{ORG5.email}>\n"
    "Date: Mon, {~MESSAGE_DATE:16 Mar 2026} 19:02:00 +0200\n"
    "Subject: Відновлення доступу\n\n"
    "Добрий день!\n\n"
    "Прошу відновити доступ до акаунта. Для перевірки: дата народження {P07.dob.uk}, адреса "
    "{P07.addr.line}, останній вхід з IP {P07.ip}.\n\n"
    "Дякую,\n{P07:Дмитро Мельник}\n{P07@org:ФОП Мельник Дмитро}\n{P07.phone.intl}\n",
    # thread_06: given name not in the gazetteer; bare first name shared by three people
    "From: {P14:Radim Kučera} <{P14.email}>\n"
    "To: {P12:Tomáš Kollár} <{P12.email}>\n"
    "Date: Tue, {~MESSAGE_DATE:17 Mar 2026} 11:30:00 +0100\n"
    "Subject: LedgerLite admin for {ORG1:Tatra Logistics}\n\n"
    "Hi {P12:Tomáš},\n\n"
    "I am taking over the LedgerLite admin role from {P01:Oleksandr}. Please send technical questions to me; "
    "my desk phone is {P14.phone.intl}.\n\n"
    "Thanks,\n{P14:Radim}\n",
]

# (handle, text) per message; handles are plain strings (see README: online identifiers).
CHATS: list[list[tuple[str, str]]] = [
    [
        ("guest_4821", "hi its {P07:dmytro}, cant open my invoices"),
        (
            "agent_07",
            "Hello, this is {P12:Tomáš} from {ORG5:Dunaj Software} support. Could you confirm the e-mail on the account?",
        ),
        ("guest_4821", "{P07.email}"),
        ("guest_4821", "and the ip is {P07.ip} if that helps"),
        ("agent_07", "Thanks {P07:Dmytro}, I have reset the session."),
        ("guest_4821", "also the invoice must be on {P07:DMYTRO MELNYK} like in my passport"),
    ],
    [
        ("guest_1093", "Hi, {P01:Sasha} here. I wrote to {ORG5.email} yesterday about the export bug."),
        ("agent_11", "Hi {P01:Sasha}, I'm {P11:Lucia}. Which version are you on?"),
        (
            "guest_1093",
            "version {~VERSION_STRING:10.2.3.4}. you can also call me at {P01.phone.plain} or write to {P01.email2}",
        ),
        ("agent_11", "Thank you, I will call you in 10 minutes."),
    ],
    [
        (
            "guest_5512",
            "Hello, {P05:Lubomir Stastny} from {ORG4:Martin Precision}. Activation fails on version {~VERSION_STRING:2.4.10.1}.",
        ),
        ("agent_07", "Hi Mr {P05:Stastny}, {P12:Tomáš} here. Please send the log file."),
        (
            "guest_5512",
            "Sent it from {P05.email}. If I'm offline, ask {P13:Michal} (his number is {P13.phone.national}).",
        ),
    ],
    [
        (
            "guest_7740",
            "Hi, it's {P06:Natasha} from {ORG3:Karpaty Food}. Did you get our payment for {~INVOICE_NUMBER:INV-2026-0042}?",
        ),
        ("agent_11", "Hello {P06:Natasha}, yes, the payment arrived on {~MESSAGE_DATE:18.03.2026}."),
        (
            "guest_7740",
            "Great. Next time please write to {P06.email} or {P06!EMAIL:n.shevchuk [at] karpaty-food.example}, not to the info box.",
        ),
    ],
    [
        ("guest_3307", "Dobrý deň, volám sa {P10:Katarína Bieliková}, zákaznícke číslo {P10.cid.num}."),
        ("agent_11", "Dobrý deň, pani {P10:Bieliková}, pre overenie prosím dátum narodenia."),
        ("guest_3307", "nar. {P10.dob.sk}, bývam na {P10.addr.street} v Bratislave."),
    ],
    [
        (
            "guest_9001",
            "Is order {~ORDER_NUMBER:ORD-2026-11902} shipped? We run build {~VERSION_STRING:10.2.3.4} on all PCs.",
        ),
        ("agent_07", "Yes, it shipped. Licences for {~PRODUCT_CODE:LX-200} are active."),
        (
            "guest_9001",
            "great, thx. we are on {~VERSION_STRING:10.2.3.4} everywhere btw. receipt to {ORG1.email} pls. our IT guy {P14:Radim} has the details",
        ),
    ],
]

INVOICE_HEADER = ["invoice_no", "client_name", "IBAN", "VAT_ID", "billing_address", "amount", "issue_date"]
# (client tag, entity key, VAT ID kind) — VAT IDs of companies are decoys; a sole trader's is left unannotated.
INVOICE_CLIENTS: list[tuple[str, str, str]] = [
    ("{P03@org:Jana Horváthová – Účtovné služby}", "P03", "sole_trader"),
    ("{ORG1:Tatra Logistics s.r.o.}", "ORG1", "company"),
    ("{ORG2:Brightwell Components Ltd}", "ORG2", "company"),
    ("{ORG3:ТОВ «Карпати Фуд»}", "ORG3", "company"),
    ("{P10:Katarína Bieliková}", "P10", "none"),
    ("{ORG4:Martin Precision s.r.o.}", "ORG4", "company"),
    ("{P01:Oleksandr Kovalenko}", "P01", "none"),
    ("{P07@org:FOP Dmytro Melnyk}", "P07", "none"),
    ("{P15:Marek Bielik}", "P15", "none"),
]


# ---------------------------------------------------------------- assembly


@dataclass
class Collected:
    gold: list[Span] = field(default_factory=list)
    decoys: list[Decoy] = field(default_factory=list)

    def add(self, doc_id: str, built: Built) -> str:
        for start, end, type_, entity_id, is_pii in built.spans:
            self.gold.append(Span(doc_id, start, end, built.text[start:end], type_, is_pii, entity_id))
        for start, end, kind in built.decoys:
            self.decoys.append(Decoy(doc_id, start, end, built.text[start:end], kind))
        return built.text


def _timestamps(rng: random.Random, count: int) -> list[datetime]:
    start = datetime(2026, 3, 2, 8, 0, 0)
    stamps = sorted(start + timedelta(minutes=rng.randint(0, 20 * 24 * 60)) for _ in range(count))
    return [stamp.replace(second=rng.randint(0, 59)) for stamp in stamps]


def _iso(stamp: datetime) -> str:
    return stamp.strftime("%Y-%m-%dT%H:%M:%SZ")


def _write_crm(out: Path, cast: dict[str, Entity], col: Collected) -> None:
    rows = []
    for row_no, cells in enumerate(CRM_ROWS, start=1):
        row = []
        for column, template in zip(CRM_HEADER, cells):
            doc_id = dataset.csv_doc_id(dataset.CRM_FILE, row_no, column)
            # A city on its own is not annotated as PII; listed as a decoy instead.
            built = decoy(template, "CITY") if column == "city" else render(template, cast)
            row.append(col.add(doc_id, built))
        rows.append(row)
    dataset.write_csv(out / dataset.CRM_FILE, CRM_HEADER, rows)


def _materialize(value: object, name: str, line: int, path: str, col: Collected) -> object:
    """Turn a record whose leaves are `Built` into plain JSON, collecting spans."""
    if isinstance(value, Built):
        return col.add(dataset.jsonl_doc_id(name, line, path), value)
    if isinstance(value, dict):
        return {k: _materialize(v, name, line, f"{path}.{k}" if path else k, col) for k, v in value.items()}
    if isinstance(value, list):
        return [_materialize(v, name, line, f"{path}.{i}", col) for i, v in enumerate(value)]
    return value


def _write_tickets(out: Path, cast: dict[str, Entity], rng: random.Random, col: Collected) -> None:
    records = []
    for line, ((subject, body), created) in enumerate(zip(TICKETS, _timestamps(rng, len(TICKETS))), start=1):
        record = {
            "ticket_id": decoy(f"T-2026-{rng.randint(100, 999):04d}", "TICKET_ID"),
            "created_at": decoy(_iso(created), "TIMESTAMP"),
            "subject": render(subject, cast),
            "body": render(body, cast),
        }
        records.append(_materialize(record, dataset.TICKETS_FILE, line, "", col))
    dataset.write_jsonl_records(out / dataset.TICKETS_FILE, records)


def _write_emails(out: Path, cast: dict[str, Entity], col: Collected) -> None:
    (out / dataset.EMAIL_DIR).mkdir(parents=True, exist_ok=True)
    for number, template in enumerate(EMAILS, start=1):
        filename = f"thread_{number:02d}.txt"
        text = col.add(dataset.email_doc_id(filename), render(template, cast))
        (out / dataset.EMAIL_DIR / filename).write_text(text, encoding="utf-8", newline="\n")


def _write_chats(out: Path, cast: dict[str, Entity], rng: random.Random, col: Collected) -> None:
    records = []
    for line, messages in enumerate(CHATS, start=1):
        stamps = _timestamps(rng, len(messages))
        record = {
            "chat_id": plain(f"CH-{line:03d}"),
            "started_at": decoy(_iso(stamps[0]), "TIMESTAMP"),
            "messages": [
                {"ts": decoy(_iso(stamp), "TIMESTAMP"), "handle": plain(handle), "text": render(text, cast)}
                for (handle, text), stamp in zip(messages, stamps)
            ],
        }
        records.append(_materialize(record, dataset.CHATS_FILE, line, "", col))
    dataset.write_jsonl_records(out / dataset.CHATS_FILE, records)


def _vat_id(rng: random.Random, entity_key: str) -> str:
    if entity_key == "ORG2":
        return "GB" + _digits(rng, 9)
    if entity_key == "ORG3":
        return "UA" + _digits(rng, 10)
    return "SK" + rng.choice(["10", "20", "21"]) + _digits(rng, 8)


def _write_invoices(out: Path, cast: dict[str, Entity], rng: random.Random, col: Collected) -> None:
    rows = []
    dates = sorted(date(2026, 2, 1) + timedelta(days=rng.randint(0, 50)) for _ in INVOICE_CLIENTS)
    for row_no, ((client, key, vat_kind), issued) in enumerate(zip(INVOICE_CLIENTS, dates), start=1):
        vat = _vat_id(rng, key)
        cells = {
            "invoice_no": decoy(f"INV-2026-{38 + row_no:04d}", "INVOICE_NUMBER"),
            "client_name": render(client, cast),
            "IBAN": render(f"{{{key}.iban.compact}}", cast),
            "VAT_ID": decoy(vat, "COMPANY_VAT_ID")
            if vat_kind == "company"
            else plain(vat if vat_kind == "sole_trader" else ""),
            "billing_address": render(f"{{{key}.addr.line}}", cast),
            "amount": decoy(f"{rng.randint(90, 9000)}.{rng.choice(['00', '50', '90'])} EUR", "AMOUNT"),
            "issue_date": decoy(issued.isoformat(), "ISSUE_DATE"),
        }
        row = [
            col.add(dataset.csv_doc_id(dataset.INVOICES_FILE, row_no, column), cells[column])
            for column in INVOICE_HEADER
        ]
        rows.append(row)
    dataset.write_csv(out / dataset.INVOICES_FILE, INVOICE_HEADER, rows)


def verify_offsets(out: Path, gold: list[Span], decoys: list[Decoy]) -> dict[str, int]:
    """Reload the written files and check every annotation against the text.

    Returns {doc_id: position in document order}; raises ValueError on a mismatch.
    """
    docs = {doc.doc_id: doc for doc in dataset.load_documents(out)}
    for item in [*gold, *decoys]:
        doc = docs.get(item.doc_id)
        if doc is None or doc.text[item.start : item.end] != item.text:
            raise ValueError(f"offset mismatch for {item}")
    return {doc_id: position for position, doc_id in enumerate(docs)}


def generate(out: Path, seed: int = 42) -> tuple[list[Span], list[Decoy]]:
    """Write the dataset, gold.jsonl and decoys.jsonl to `out`."""
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    rng = random.Random(seed)
    cast = build_cast(rng)
    col = Collected()
    _write_crm(out, cast, col)
    _write_tickets(out, cast, rng, col)
    _write_emails(out, cast, col)
    _write_chats(out, cast, rng, col)
    _write_invoices(out, cast, rng, col)
    order = verify_offsets(out, col.gold, col.decoys)
    gold = sorted(col.gold, key=lambda s: (order[s.doc_id], s.start))
    decoys = sorted(col.decoys, key=lambda d: (order[d.doc_id], d.start))
    write_jsonl(out / "gold.jsonl", (span.to_gold_dict() for span in gold))
    write_jsonl(out / "decoys.jsonl", (d.to_dict() for d in decoys))
    return gold, decoys
