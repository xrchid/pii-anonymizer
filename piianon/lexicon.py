"""Small bundled word lists used by the detectors and the resolver.

All entries are stored in normalized form: lower case, ASCII, with Ukrainian
Cyrillic transliterated (see `resolve.normalize_name`). Cyrillic spellings
therefore do not need separate entries: "Олександр" normalizes to "oleksandr".

The lists are deliberately short. They cover the languages in the synthetic
dataset (English, Slovak, Ukrainian) and are meant to be read and extended,
not to be a complete name database.
"""

from __future__ import annotations

# Canonical first name -> spellings, transliterations and nicknames that refer
# to the same given name. Used for gazetteer lookup and for linking "Sasha" or
# "Alexander" to "Oleksandr".
NAME_GROUPS: dict[str, tuple[str, ...]] = {
    "oleksandr": ("oleksandr", "olexandr", "aleksandr", "alexander", "alexandr", "alex", "sasha", "sashko"),
    "nataliia": ("nataliia", "natalia", "nataliya", "natalya", "natasha", "natalka"),
    "dmytro": ("dmytro", "dmitry", "dmitriy", "dmitrii", "dima"),
    "katarina": ("katarina", "katka", "katarinka"),
    "lubomir": ("lubomir", "lubo", "lubko"),
    "peter": ("peter", "peto", "petr", "petro"),
    "tomas": ("tomas", "tomi", "tomasko"),
    "michal": ("michal", "miso"),
    "jana": ("jana", "janka"),
    "lucia": ("lucia", "lucka"),
    "zuzana": ("zuzana", "zuzka"),
    "iryna": ("iryna", "irina", "ira"),
    "olena": ("olena", "elena", "lena"),
    "andrii": ("andrii", "andriy", "andrei"),
    "serhii": ("serhii", "serhiy", "sergey", "sergei"),
    "mykola": ("mykola", "nikolai", "kolia"),
    "yuliia": ("yuliia", "yulia", "yuliya"),
    "kateryna": ("kateryna", "katia", "katya"),
    # "Will", "Bill" and "Jan" (January) are left out on purpose: as capitalized
    # words they are more often not names.
    "william": ("william", "willy"),
    "robert": ("robert", "rob"),
    "elizabeth": ("elizabeth", "liz", "beth"),
}

# Given names with no variants we care about.
SINGLE_FIRST_NAMES: frozenset[str] = frozenset(
    {
        # English
        "emily", "emma", "olivia", "sophie", "sarah", "jessica", "laura", "hannah", "rachel",
        "charlotte", "amelia", "lucy", "chloe", "james", "john", "michael", "david", "richard",
        "joseph", "thomas", "daniel", "matthew", "anthony", "paul", "steven", "andrew", "oliver",
        "harry", "george", "jack", "edward", "henry",
        # Slovak / Czech
        "martin", "marek", "juraj", "lukas", "matej", "jakub", "filip", "adam", "patrik",
        "stefan", "jozef", "pavol", "miroslav", "vladimir", "stanislav", "igor", "dusan", "ladislav",
        "eva", "maria", "monika", "ivana", "petra", "lenka", "simona", "veronika", "barbora",
        "kristina", "dominika", "michaela", "andrea", "silvia", "alena", "viera", "beata", "zdenka",
        "andrej",
        # Ukrainian (Latin transliteration; Cyrillic normalizes to these)
        "taras", "bohdan", "viktor", "yurii", "vasyl", "oksana", "halyna", "liudmyla", "tetiana",
        "svitlana", "mariia", "anastasiia", "viktoriia", "maksym", "artem", "denys", "volodymyr",
        "pavlo", "oleh", "ihor", "vitalii", "ivan",
    }
)

# Every spelling -> canonical form.
CANONICAL_FIRST: dict[str, str] = {
    **{name: name for name in SINGLE_FIRST_NAMES},
    **{variant: canonical for canonical, variants in NAME_GROUPS.items() for variant in variants},
}

FIRST_NAMES: frozenset[str] = frozenset(CANONICAL_FIRST)

# Honorifics and academic titles that precede a name but are not part of it.
# Includes Slovak "pán/pani" and Ukrainian "пан/пані" with common case forms.
TITLES: frozenset[str] = frozenset(
    {
        "mr", "mrs", "ms", "miss", "dr", "ing", "mgr", "bc", "prof",
        # normalized Slovak/Ukrainian forms and the raw spellings (for casefold-only checks)
        "pan", "pana", "pane", "panu", "panom", "pani", "pán", "pána", "pánovi", "pánom",
        "пан", "пана", "пане", "пані",
    }
)

# Capitalized words that are never part of a person's name in this domain.
STOPWORDS: frozenset[str] = frozenset(
    {
        "support", "team", "customer", "customers", "client", "sir", "madam", "all", "there",
        "everyone", "colleagues", "manager", "operations", "finance", "procurement", "sales",
        "billing", "accounting", "office", "reception", "the", "and", "from", "to", "re", "fw",
        "fwd", "subject", "thanks", "thank", "regards", "best", "kind", "dear", "hi", "hello",
        "hey", "cheers", "ltd", "llc", "inc", "gmbh", "plc", "software", "logistics", "components",
        "food", "precision", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday",
        "sunday", "january", "february", "march", "april", "may", "june", "july", "august",
        "september", "october", "november", "december", "please", "our", "your", "my", "we",
        "ceo", "cfo", "it", "api", "csv", "iban", "invoice", "order", "version", "build",
    }
)

# Words that mark the text after "Name – ..." as a job title rather than a
# sole trader's business name ("Lucia Benková – Customer Success").
JOB_TITLE_WORDS: frozenset[str] = frozenset(
    {
        "manager", "lead", "head", "director", "officer", "assistant", "specialist", "support",
        "success", "engineer", "developer", "accountant", "ceo", "cfo", "cto", "consultant",
        "intern", "team", "procurement", "finance", "operations", "sales", "hr",
    }
)

# Closing phrases that start a signature block (compared case-insensitively).
CLOSINGS: tuple[str, ...] = (
    "best regards", "kind regards", "warm regards", "regards", "best wishes", "best", "thanks",
    "thank you", "many thanks", "cheers", "sincerely", "yours sincerely",
    "s pozdravom", "s pozdravem", "s úctou", "ďakujem",
    "з повагою", "дякую", "з найкращими побажаннями",
)

# Greetings that are usually followed by the addressee's name.
GREETINGS: tuple[str, ...] = (
    "hi", "hello", "hey", "dear", "good morning", "good afternoon",
    "ahoj", "dobrý deň", "dobry den", "привіт", "добрий день", "вітаю", "шановний", "шановна",
)

# First-person words (English, Slovak, Ukrainian). A sentence containing one
# usually talks about the writer ("my date of birth is ...").
FIRST_PERSON_WORDS: frozenset[str] = frozenset(
    {
        "i", "i'm", "i’m", "me", "my", "mine", "we", "our", "us",
        "som", "môj", "moja", "moje", "mňa", "mi", "náš", "naša", "naše", "nás",
        "я", "мій", "моя", "моє", "мої", "мене", "мені", "наш", "наша", "наше", "нас",
    }
)

# Local parts of shared/role mailboxes. Such addresses identify a function of
# an organization, not a natural person.
ROLE_LOCAL_PARTS: frozenset[str] = frozenset(
    {
        "info", "support", "help", "helpdesk", "sales", "billing", "invoices", "invoice",
        "accounts", "accounting", "office", "admin", "administrator", "contact", "hello", "team",
        "noreply", "no-reply", "donotreply", "postmaster", "webmaster", "hr", "jobs", "careers",
        "press", "marketing", "orders", "service", "reception", "security", "it",
    }
)

# Ukrainian national transliteration (Cabinet of Ministers resolution No. 55,
# 2010). Second value is used at the start of a word. Russian-only letters are
# added so mixed texts still normalize.
UK_TRANSLIT: dict[str, tuple[str, str]] = {
    "а": ("a", "a"), "б": ("b", "b"), "в": ("v", "v"), "г": ("h", "h"), "ґ": ("g", "g"),
    "д": ("d", "d"), "е": ("e", "e"), "є": ("ie", "ye"), "ж": ("zh", "zh"), "з": ("z", "z"),
    "и": ("y", "y"), "і": ("i", "i"), "ї": ("i", "yi"), "й": ("i", "y"), "к": ("k", "k"),
    "л": ("l", "l"), "м": ("m", "m"), "н": ("n", "n"), "о": ("o", "o"), "п": ("p", "p"),
    "р": ("r", "r"), "с": ("s", "s"), "т": ("t", "t"), "у": ("u", "u"), "ф": ("f", "f"),
    "х": ("kh", "kh"), "ц": ("ts", "ts"), "ч": ("ch", "ch"), "ш": ("sh", "sh"),
    "щ": ("shch", "shch"), "ь": ("", ""), "ю": ("iu", "yu"), "я": ("ia", "ya"),
    "'": ("", ""), "’": ("", ""), "ʼ": ("", ""),
    # Russian letters (not in the Ukrainian alphabet)
    "ё": ("io", "yo"), "ъ": ("", ""), "ы": ("y", "y"), "э": ("e", "e"),
}

MONTHS_EN: dict[str, int] = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6, "july": 7,
    "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6, "jul": 7, "aug": 8, "sep": 9, "sept": 9,
    "oct": 10, "nov": 11, "dec": 12,
}
# Genitive forms as used in dates ("3. mája 1985", "7 листопада 1990").
MONTHS_SK: dict[str, int] = {
    "januára": 1, "februára": 2, "marca": 3, "apríla": 4, "mája": 5, "júna": 6, "júla": 7,
    "augusta": 8, "septembra": 9, "októbra": 10, "novembra": 11, "decembra": 12,
}
MONTHS_UK: dict[str, int] = {
    "січня": 1, "лютого": 2, "березня": 3, "квітня": 4, "травня": 5, "червня": 6, "липня": 7,
    "серпня": 8, "вересня": 9, "жовтня": 10, "листопада": 11, "грудня": 12,
}
MONTHS: dict[str, int] = {**MONTHS_EN, **MONTHS_SK, **MONTHS_UK}
