"""Transliteration, diacritics and nickname normalization."""

import unittest

from piianon.resolve import canonical_first_name, normalize_name, strip_diacritics, transliterate


class TransliterationTest(unittest.TestCase):
    def test_ukrainian_names(self) -> None:
        cases = {
            "Олександр Коваленко": "oleksandr kovalenko",
            "Наталія Шевчук": "nataliia shevchuk",
            "Дмитро Мельник": "dmytro melnyk",
            "Юрій": "yurii",  # ю at word start -> yu, й at word end -> i
            "Єва": "yeva",
            "Згурський": "zghurskyi",  # зг -> zgh
            "Мар'яна": "mariana",  # apostrophe dropped, я after it is not word-initial
            "Щербак": "shcherbak",
        }
        for cyrillic, latin in cases.items():
            with self.subTest(cyrillic=cyrillic):
                self.assertEqual(transliterate(cyrillic), latin)

    def test_latin_text_is_only_lower_cased(self) -> None:
        self.assertEqual(transliterate("Peter Novák"), "peter novák")


class NormalizationTest(unittest.TestCase):
    def test_strip_diacritics(self) -> None:
        self.assertEqual(strip_diacritics("Ľubomír Šťastný"), "Lubomir Stastny")
        self.assertEqual(strip_diacritics("Horváthová"), "Horvathova")

    def test_scripts_and_spellings_meet(self) -> None:
        self.assertEqual(normalize_name("Олександр Коваленко"), normalize_name("OLEKSANDR  KOVALENKO"))
        self.assertEqual(normalize_name("Ľubomír Šťastný"), normalize_name("Lubomir Stastny"))
        self.assertEqual(normalize_name("Tomáš Kollár"), "tomas kollar")

    def test_nicknames_map_to_canonical_name(self) -> None:
        for name in ("Oleksandr", "Alexander", "Sasha", "Alex", "Олександр", "Саша"):
            with self.subTest(name=name):
                self.assertEqual(canonical_first_name(name), "oleksandr")
        self.assertEqual(canonical_first_name("Natasha"), "nataliia")
        self.assertEqual(canonical_first_name("Наталія"), "nataliia")
        self.assertEqual(canonical_first_name("Katka"), "katarina")
        self.assertEqual(canonical_first_name("Peťo"), "peter")
        self.assertEqual(canonical_first_name("Діма"), "dmytro")

    def test_unknown_word_has_no_canonical_name(self) -> None:
        self.assertIsNone(canonical_first_name("Radim"))
        self.assertIsNone(canonical_first_name("Kovalenko"))


if __name__ == "__main__":
    unittest.main()
