"""Each detector on tricky positive and negative examples, including decoys."""

import unittest

from piianon.dataset import Document
from piianon.detect import (
    EMPTY_LEXICON,
    Lexicon,
    apply_company_record_rule,
    detect_document,
    detect_text,
    find_addresses,
    find_customer_ids,
    find_dates_of_birth,
    find_emails,
    find_ipv4,
    find_organizations,
    find_person_names,
    find_sole_traders,
)


def texts(spans: list) -> list[str]:
    return [span.text for span in spans]


def typed(text: str, lex: Lexicon = EMPTY_LEXICON) -> list[tuple[str, str, bool]]:
    return [(s.type, s.text, s.is_pii) for s in detect_text(text, lex)]


class EmailTest(unittest.TestCase):
    def test_personal_and_role_mailboxes(self) -> None:
        spans = find_emails("Write to o.kovalenko@tatra.example or support@dunajsoft.example.")
        self.assertEqual(
            [(s.text, s.is_pii) for s in spans],
            [("o.kovalenko@tatra.example", True), ("support@dunajsoft.example", False)],
        )

    def test_address_in_angle_brackets_and_sentence_end(self) -> None:
        self.assertEqual(
            texts(find_emails("From: Emily <emily.carter@brightwell.example>.")), ["emily.carter@brightwell.example"]
        )

    def test_obfuscated_address_is_not_found(self) -> None:
        self.assertEqual(find_emails("n.shevchuk [at] karpaty-food.example"), [])


class IpTest(unittest.TestCase):
    def test_ip_found(self) -> None:
        self.assertEqual(texts(find_ipv4("login from 203.0.113.45 at night")), ["203.0.113.45"])

    def test_version_strings_and_invalid_octets_skipped(self) -> None:
        for text in (
            "update to version 10.2.3.4",
            "build 4.12.0.1",
            "v10.2.3.4",
            "fw 1.0.0.12",
            "999.1.1.1",
            "10.02.3.4",
        ):
            with self.subTest(text=text):
                self.assertEqual(find_ipv4(text), [])

    def test_version_without_keyword_is_a_false_positive(self) -> None:
        # Known limitation: without a context word a version looks like an IP.
        self.assertEqual(texts(find_ipv4("we are on 10.2.3.4 everywhere")), ["10.2.3.4"])


class DateOfBirthTest(unittest.TestCase):
    def test_with_context(self) -> None:
        cases = {
            "Born 12.04.1988.": "12.04.1988",
            "my date of birth is 1988-04-12": "1988-04-12",
            "Date of birth 14 February 1987": "14 February 1987",
            "nar. 3. mája 1985": "3. mája 1985",
            "Dátum narodenia: 03.05.1985": "03.05.1985",
            "дата народження 7 листопада 1990": "7 листопада 1990",
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(texts(find_dates_of_birth(text)), [expected])

    def test_other_dates_are_not_birth_dates(self) -> None:
        for text in (
            "created 2026-03-14T09:12:00Z",
            "On 12.03.2026 Lucia wrote:",
            "issued 1988-04-12",
            "born 31.02.1988",
            "born 12.04.2024",
        ):
            with self.subTest(text=text):
                self.assertEqual(find_dates_of_birth(text), [])


class CustomerIdTest(unittest.TestCase):
    def test_prefixed_and_contextual(self) -> None:
        self.assertEqual(texts(find_customer_ids("Our customer number is C-10042.")), ["C-10042"])
        self.assertEqual(texts(find_customer_ids("under my customer number 46048")), ["46048"])
        self.assertEqual(texts(find_customer_ids("zákaznícke číslo 81482")), ["81482"])

    def test_other_codes_are_ignored(self) -> None:
        text = "ORD-2026-11873, INV-2026-0042, T-2026-0412, PC-20431, BX-4410-22, 46048 seats"
        self.assertEqual(find_customer_ids(text), [])


class OrganizationTest(unittest.TestCase):
    def test_limited_companies_are_not_personal(self) -> None:
        text = "Operations Manager, Tatra Logistics s.r.o.\nCustomer Success, Dunaj Software a.s. and ТОВ «Карпати Фуд»"
        spans = find_organizations(text)
        self.assertEqual(
            [(s.text, s.is_pii) for s in spans],
            [("Tatra Logistics s.r.o.", False), ("Dunaj Software a.s.", False), ("ТОВ «Карпати Фуд»", False)],
        )

    def test_ukrainian_sole_trader_is_personal(self) -> None:
        spans = find_organizations("I am a sole trader (ФОП Мельник Дмитро), invoice FOP Dmytro Melnyk.")
        self.assertEqual(
            [(s.text, s.is_pii) for s in spans], [("ФОП Мельник Дмитро", True), ("FOP Dmytro Melnyk", True)]
        )

    def test_slovak_sole_trader_vs_job_title(self) -> None:
        text = "Jana Horváthová – Účtovné služby, and Lucia Benková – Customer Success"
        traders = find_sole_traders(text, find_person_names(text))
        self.assertEqual(texts(traders), ["Jana Horváthová – Účtovné služby"])

    def test_known_company_without_legal_form(self) -> None:
        lex = Lexicon(org_names=("Martin Precision",))
        self.assertIn(("ORGANIZATION", "Martin Precision", False), typed("Regards,\nMartin Precision IT", lex))


class PersonTest(unittest.TestCase):
    def test_gazetteer_names_in_several_scripts(self) -> None:
        text = "Oleksandr Kovalenko, Наталія Шевчук, Ľubomír Šťastný and Katka met."
        self.assertEqual(
            texts(find_person_names(text)), ["Oleksandr Kovalenko", "Наталія Шевчук", "Ľubomír Šťastný", "Katka"]
        )

    def test_titles_greetings_signatures_headers(self) -> None:
        self.assertIn("Kovalenko", texts(find_person_names("Dear Mr Kovalenko,")))
        self.assertIn("Benková", texts(find_person_names("Dobrý deň, pani Benková,")))
        self.assertIn("Олександре", texts(find_person_names("Привіт, Олександре!")))
        self.assertIn("Radim Kučera", texts(find_person_names("Thanks,\nRadim Kučera\nIT")))
        self.assertIn("Radim Kučera", texts(find_person_names("From: Radim Kučera <r.kucera@tatra.example>")))

    def test_non_names_are_skipped(self) -> None:
        for text in (
            "Dear Customer,",
            "Dear Support Team,",
            "To: Dunaj Support <support@dunajsoft.example>",
            "Hello, this is about the export.",
            "Hi all,",
        ):
            with self.subTest(text=text):
                self.assertEqual(find_person_names(text), [])

    def test_lower_case_and_capitals_are_missed(self) -> None:
        # Known limitations, kept visible in the evaluation.
        self.assertEqual(find_person_names("hi its dmytro"), [])
        self.assertEqual(find_person_names("on name DMYTRO MELNYK like in my passport"), [])

    def test_learned_surname_and_initial(self) -> None:
        lex = Lexicon(surnames=frozenset({"kovalenko"}))
        self.assertEqual(
            texts(find_person_names("took over from O. Kovalenko; ask Kovalenko", lex)), ["O. Kovalenko", "Kovalenko"]
        )

    def test_first_name_city_is_a_false_positive(self) -> None:
        # Known limitation: "Martin" is both a first name and a Slovak city.
        self.assertEqual(texts(find_person_names("Martin")), ["Martin"])


class AddressTest(unittest.TestCase):
    def test_addresses(self) -> None:
        cases = {
            "Invoices to Hlavná 12, 040 01 Košice. Thanks": "Hlavná 12, 040 01 Košice",
            "Lives at Štúrova 5/A, 811 02 Bratislava last year": "Štúrova 5/A, 811 02 Bratislava",
            "Jana\nHlavná 12\n040 01 Košice\n": "Hlavná 12\n040 01 Košice",
            "office: Južná trieda 48, 040 01 Košice": "Južná trieda 48, 040 01 Košice",
            "is Unit 4, Riverside Park, Leeds LS11 5QT.": "Unit 4, Riverside Park, Leeds LS11 5QT",
            "home: 27 Elm Grove, Leeds LS6 2AB": "27 Elm Grove, Leeds LS6 2AB",
            "адреса вул. Шевченка, 15, Львів, 79000.": "вул. Шевченка, 15, Львів, 79000",
            "bývam na Štúrova 5/A v Bratislave": "Štúrova 5/A",
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(texts(find_addresses(text)), [expected])

    def test_word_and_number_pairs_are_not_addresses(self) -> None:
        for text in (
            "upgrade to version 12 now",
            "Windows 11",
            "Room 4",
            "we need 5 more seats",
            "Košice",
            "040 01 Košice",
        ):
            with self.subTest(text=text):
                self.assertEqual(find_addresses(text), [])


class CombinedTest(unittest.TestCase):
    def test_decoys_in_one_text(self) -> None:
        text = (
            "Dear Customer, your order ORD-2026-11873 (invoice INV-2026-0042, 4 860.00 GBP, issued 12.03.2026) "
            "ships with version 10.2.3.4. Product BX-4410-22. Questions: info@tatra-logistics.example, "
            "Tatra Logistics s.r.o."
        )
        self.assertEqual([t for t in typed(text) if t[2]], [])

    def test_column_hints(self) -> None:
        def doc(field: str, value: str) -> Document:
            return Document(f"invoices.csv:1:{field}", value, "invoices.csv:1", field)

        self.assertEqual(typed_doc(doc("client_name", "Tatra Logistics s.r.o.")), [("ORGANIZATION", False)])
        self.assertEqual(typed_doc(doc("client_name", "Katarína Bieliková")), [("PERSON", True)])
        self.assertEqual(typed_doc(doc("client_name", "Jana Horváthová – Účtovné služby")), [("ORGANIZATION", True)])
        self.assertEqual(typed_doc(doc("client_name", "FOP Dmytro Melnyk")), [("ORGANIZATION", True)])

    def test_company_record_rule(self) -> None:
        docs = [
            Document("invoices.csv:1:client_name", "Tatra Logistics s.r.o.", "invoices.csv:1", "client_name"),
            Document(
                "invoices.csv:1:billing_address", "Južná trieda 48, 040 01 Košice", "invoices.csv:1", "billing_address"
            ),
            Document("invoices.csv:2:client_name", "Katarína Bieliková", "invoices.csv:2", "client_name"),
            Document(
                "invoices.csv:2:billing_address", "Štúrova 5/A, 811 02 Bratislava", "invoices.csv:2", "billing_address"
            ),
            Document("note", "Ship to Južná trieda 48, 040 01 Košice.", "note", "body"),
        ]
        spans = apply_company_record_rule([s for d in docs for s in detect_document(d)], docs)
        addresses = {(s.doc_id, s.is_pii) for s in spans if s.type == "ADDRESS"}
        self.assertEqual(
            addresses,
            {("invoices.csv:1:billing_address", False), ("invoices.csv:2:billing_address", True), ("note", False)},
        )


def typed_doc(doc: Document) -> list[tuple[str, bool]]:
    return [(s.type, s.is_pii) for s in detect_document(doc)]


if __name__ == "__main__":
    unittest.main()
