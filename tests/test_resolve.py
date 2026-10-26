"""Name keys, nickname/initial/e-mail linking and the over-merge guard."""

import unittest

from piianon.dataset import Document
from piianon.detect import detect_dataset
from piianon.resolve import NameKey, compatible, email_name_key, matches, name_key, resolve


def _docs(*texts: str) -> list[Document]:
    return [Document(f"doc{i}", text, f"doc{i}", "") for i, text in enumerate(texts)]


def _clusters(*texts: str) -> dict[str, set[str]]:
    """{surface text: set of cluster labels} for PII spans of the given texts."""
    docs = _docs(*texts)
    result: dict[str, set[str]] = {}
    for span in resolve(detect_dataset(docs), docs):
        if span.is_pii:
            result.setdefault(span.text, set()).add(span.entity_id)
    return result


class NameKeyTest(unittest.TestCase):
    def test_initial_and_surname(self) -> None:
        self.assertEqual(name_key("O. Kovalenko"), NameKey(surname="kovalenko", initial="o"))

    def test_surname_first_order(self) -> None:
        self.assertEqual(name_key("Мельник Дмитро"), NameKey(first="dmytro", surname="melnyk"))

    def test_nickname_is_canonical(self) -> None:
        self.assertEqual(name_key("Sasha"), NameKey(first="oleksandr"))
        self.assertEqual(name_key("Alexander Kovalenko"), name_key("Олександр Коваленко"))

    def test_single_unknown_word(self) -> None:
        self.assertEqual(name_key("Radim"), NameKey(word="radim"))

    def test_email_local_parts(self) -> None:
        self.assertEqual(email_name_key("o.kovalenko@x.example"), NameKey(surname="kovalenko", initial="o"))
        self.assertEqual(email_name_key("horvathova.jana@x.example"), NameKey(first="jana", surname="horvathova"))
        self.assertEqual(email_name_key("katka.bielikova@x.example"), NameKey(first="katarina", surname="bielikova"))
        self.assertEqual(email_name_key("sasha.k92@x.example"), NameKey(first="oleksandr"))
        self.assertIsNone(email_name_key("info@x.example"))

    def test_initial_matching(self) -> None:
        full = NameKey(first="oleksandr", surname="kovalenko")
        self.assertTrue(matches(NameKey(surname="kovalenko", initial="o"), full))
        self.assertTrue(matches(NameKey(surname="kovalenko", initial="a"), full))  # Alexander
        self.assertFalse(matches(NameKey(surname="kovalenko", initial="n"), full))
        self.assertFalse(matches(NameKey(surname="bondarenko", initial="o"), full))

    def test_compatibility(self) -> None:
        kovalenko = NameKey(first="oleksandr", surname="kovalenko")
        self.assertFalse(compatible(kovalenko, NameKey(first="oleksandr", surname="bondarenko")))
        self.assertTrue(compatible(kovalenko, NameKey(first="oleksandr")))
        self.assertFalse(compatible(kovalenko, NameKey(word="kovalenka")))  # inflected form


class LinkingTest(unittest.TestCase):
    def test_variants_initials_and_phone_formats_link(self) -> None:
        clusters = _clusters(
            "Best regards,\nOleksandr Kovalenko\n+421 905 123 456",
            "Please forward it to O. Kovalenko.",
            "Call Sasha on 0905123456.",
            "From: Олександр Коваленко <o.kovalenko@tatra.example>",
        )
        labels = set.union(*clusters.values())
        self.assertEqual(len(labels), 1, clusters)

    def test_email_local_part_links_to_name(self) -> None:
        clusters = _clusters("Jana Horváthová signed the contract.", "Reply to horvathova.jana@ucto.example please.")
        self.assertEqual(clusters["Jana Horváthová"], clusters["horvathova.jana@ucto.example"])

    def test_same_first_name_is_not_merged(self) -> None:
        clusters = _clusters(
            "Kind regards,\nOleksandr Kovalenko\n+421 905 123 456",
            "Kind regards,\nOleksandr Bondarenko\n+380 67 123 4567",
            "Oleksandr will call tomorrow.",  # ambiguous: two people share the name
        )
        self.assertNotEqual(clusters["Oleksandr Kovalenko"], clusters["Oleksandr Bondarenko"])
        self.assertTrue(
            clusters["Oleksandr"].isdisjoint(clusters["Oleksandr Kovalenko"] | clusters["Oleksandr Bondarenko"])
        )

    def test_bare_first_name_joins_the_only_candidate_in_record(self) -> None:
        clusters = _clusters(
            "Hi Oleksandr,\n\nthe file is attached.\n\nTo: Oleksandr Bondarenko <ob@karpaty.example>",
            "Kind regards,\nOleksandr Kovalenko",
        )
        self.assertEqual(clusters["Oleksandr"], clusters["Oleksandr Bondarenko"])

    def test_shared_phone_does_not_merge_two_people(self) -> None:
        clusters = _clusters(
            "Best regards,\nPeter Novák\n+421 905 111 222",
            "Best regards,\nMichal Varga\n+421 905 111 222",  # e.g. a shared office line
        )
        self.assertNotEqual(clusters["Peter Novák"], clusters["Michal Varga"])

    def test_first_person_sentence_links_to_signer_but_not_colleague(self) -> None:
        clusters = _clusters(
            "Hello,\n\nmy date of birth is 12.04.1988. Please call my colleague Michal Varga on 0905 999 888.\n\n"
            "Regards,\nPeter Novák"
        )
        self.assertEqual(clusters["12.04.1988"], clusters["Peter Novák"])
        self.assertNotEqual(clusters["0905 999 888"], clusters["Peter Novák"])


if __name__ == "__main__":
    unittest.main()
