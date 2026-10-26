"""IBAN validation and phone normalization."""

import unittest

from piianon.detect import find_ibans, find_phones, iban_is_valid, normalize_phone
from piianon.synth import make_iban


class IbanTest(unittest.TestCase):
    def test_published_example_is_valid(self) -> None:
        self.assertTrue(iban_is_valid("GB82 WEST 1234 5698 7654 32"))

    def test_generated_ibans_are_valid(self) -> None:
        for country, bban in (
            ("SK", "99010000001234567890"),
            ("UA", "3999990000012345678901234"),
            ("GB", "ZZBK12345612345678"),
        ):
            with self.subTest(country=country):
                self.assertTrue(iban_is_valid(make_iban(country, bban)))

    def test_changed_digit_fails_checksum(self) -> None:
        iban = make_iban("SK", "99010000001234567890")
        broken = iban[:-1] + ("1" if iban[-1] != "1" else "2")
        self.assertFalse(iban_is_valid(broken))

    def test_wrong_length_and_unknown_country(self) -> None:
        self.assertFalse(iban_is_valid(make_iban("SK", "9901000000123456789")))  # 23 chars
        self.assertFalse(iban_is_valid("XX00 1234 5678"))

    def test_lower_case_and_spaces_are_accepted(self) -> None:
        self.assertTrue(iban_is_valid("gb82 west 1234 5698 7654 32"))

    def test_find_spaced_and_compact(self) -> None:
        iban = make_iban("SK", "99020000005146270482")
        spaced = " ".join(iban[i : i + 4] for i in range(0, 24, 4))
        spans = find_ibans(f"Pay to {spaced} or {iban}.")
        self.assertEqual([s.text for s in spans], [spaced, iban])
        self.assertEqual({s.value for s in spans}, {iban})

    def test_trailing_word_is_not_swallowed(self) -> None:
        iban = make_iban("SK", "99020000005146270482")
        spaced = " ".join(iban[i : i + 4] for i in range(0, 24, 4))
        spans = find_ibans(f"IBAN {spaced} VAT 12")
        self.assertEqual([s.text for s in spans], [spaced])

    def test_vat_id_and_bad_checksum_are_ignored(self) -> None:
        self.assertEqual(find_ibans("VAT ID SK1023456789"), [])
        self.assertEqual(find_ibans("SK00 9902 0000 0051 4627 0482"), [])


class PhoneTest(unittest.TestCase):
    def test_slovak_formats_normalize_to_one_number(self) -> None:
        for raw in (
            "+421 905 123 456",
            "+421905123456",
            "00421 905 123 456",
            "0905 123 456",
            "0905123456",
            "(0905) 123-456",
            "0905/123 456",
            "0905-123-456",
        ):
            with self.subTest(raw=raw):
                self.assertEqual(normalize_phone(raw), "+421905123456")

    def test_other_countries(self) -> None:
        self.assertEqual(normalize_phone("+44 7700 900461"), "+447700900461")
        self.assertEqual(normalize_phone("07700 900461"), "+447700900461")
        self.assertEqual(normalize_phone("+380 67 123 4567"), "+380671234567")
        self.assertEqual(normalize_phone("+421 2 5555 0101"), "+421255550101")

    def test_ukrainian_national_format_is_read_as_slovak(self) -> None:
        # Known limitation: without a country code, a leading 0 is read as Slovak.
        self.assertEqual(normalize_phone("067 123 45 67"), "+421671234567")

    def test_rejects_numbers_that_are_not_phones(self) -> None:
        for raw in (
            "2026000123",
            "12.04.1988",
            "+421 905 12",
            "+421 905 123 456 789",
            "1234567890",
            "+999 123 456 789",
        ):
            with self.subTest(raw=raw):
                self.assertIsNone(normalize_phone(raw))

    def test_find_phones_skips_decoys(self) -> None:
        text = (
            "Order ORD-2026-11873, invoice 2026/000123, total 1 240,00 EUR, version 10.2.3.4, "
            "born 12.04.1988, created 2026-03-14T09:12:00Z, IP 192.168.14.203."
        )
        self.assertEqual(find_phones(text), [])

    def test_find_phones_in_text(self) -> None:
        text = "Call (0905) 123-456 or +44 7700 900461; fax 02/5555 0101."
        self.assertEqual([s.value for s in find_phones(text)], ["+421905123456", "+447700900461", "+421255550101"])


if __name__ == "__main__":
    unittest.main()
