"""Layout cues in free text: quoted lines, signature blocks, e-mail headers.

These functions only look at the shape of the text. They return character
ranges; deciding whether a range is a name is left to the caller. Both the
detector (to find names) and the resolver (to decide which mentions belong
together) use them.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from . import lexicon

# Leading "> " quote markers of replied e-mails, possibly nested ("> > ").
_QUOTE_PREFIX_RE = re.compile(r"^(?:[ \t]*>)*[ \t]*")

_CLOSING_RE = re.compile(
    r"^(?:%s)(?![^\W\d_])[ \t]*[,!.]?[ \t]*(?P<rest>.*?)[ \t]*$"
    % "|".join(re.escape(c) for c in sorted(lexicon.CLOSINGS, key=len, reverse=True)),
    re.IGNORECASE,
)

# Lines that start a quoted earlier message; a signature block ends there.
_QUOTE_HEADER_RE = re.compile(r"^(?:On\s.*wrote:|From:|-{3,}|_{3,}|Sent:|Від:|Od:)", re.IGNORECASE)

# "Display Name <address@example.com>" as in From/To/Cc headers.
_NAME_EMAIL_RE = re.compile(r"(?P<name>[^\W\d_][^<>\n,:;]*?)[ \t]*<(?P<email>[^<>\s@]+@[^<>\s]+)>")

# "On 12.03.2026 17:20, Name <address> wrote:" / "On 12.03.2026 Name wrote:"
_WROTE_RE = re.compile(
    r"^On\s[^\n]*?\d{4}(?:,?\s+\d{1,2}:\d{2})?,?\s+(?P<name>[^\W\d_][^<>\n]*?)\s*(?:<[^<>\n]+>\s*)?wrote:\s*$"
)

_SELF_INTRO_RE = re.compile(
    r"(?:\b(?:I'm|I am|my name is|My name is|this is|This is|it's|It's|volám sa|Volám sa)|"
    r"(?:мене звати|Мене звати))[ \t]+(?P<name>[^\W\d_]+(?:[ \t][^\W\d_]+)?)"
)
_HERE_RE = re.compile(r"(?P<name>[^\W\d_]+(?:[ \t][^\W\d_]+)?)[ \t]+here\b")

_WORD_RE = re.compile(r"[^\W\d_]+(?:['’\-][^\W\d_]+)*")


@dataclass(frozen=True)
class Line:
    """One line of text. `content` is the line without quote markers."""

    start: int
    end: int
    content_start: int
    content: str

    @property
    def is_blank(self) -> bool:
        return not self.content.strip()


def split_lines(text: str) -> list[Line]:
    lines: list[Line] = []
    pos = 0
    for raw in text.split("\n"):
        prefix = _QUOTE_PREFIX_RE.match(raw)
        cut = prefix.end() if prefix else 0
        lines.append(Line(pos, pos + len(raw), pos + cut, raw[cut:]))
        pos += len(raw) + 1
    return lines


def is_capitalized(word: str) -> bool:
    """'Kovalenko', 'Ľubomír', 'Олександр' -> True; 'IT', 'support', 'O' -> False."""
    return word[:1].isupper() and any(ch.islower() for ch in word[1:])


def name_like_range(text: str, start: int, end: int, max_words: int = 3) -> tuple[int, int] | None:
    """Return the range of a name written in [start, end), or None.

    Accepts 1..max_words capitalized words separated by single spaces, after
    an optional leading dash ("– Sasha") and an optional title ("Ing.").
    """
    words = list(_WORD_RE.finditer(text, start, end))
    title = words.pop(0) if words and words[0].group().casefold() in lexicon.TITLES else None
    if not 1 <= len(words) <= max_words:
        return None
    prefix = text[start : words[0].start()]
    if title is not None:
        prefix = prefix.replace(title.group(), "", 1)
    if prefix.strip(" \t–-.") or text[words[-1].end() : end].strip(" \t.,!"):
        return None
    for left, right in zip(words, words[1:]):
        if text[left.end() : right.start()] != " ":
            return None
    for word in words:
        if not is_capitalized(word.group()) or word.group().casefold() in lexicon.STOPWORDS:
            return None
    return words[0].start(), words[-1].end()


def signature_name_ranges(text: str) -> list[tuple[int, int]]:
    """Names written under (or right after) a closing such as "Best regards,"."""
    found: list[tuple[int, int]] = []
    lines = split_lines(text)
    for index, line in enumerate(lines):
        match = _CLOSING_RE.match(line.content)
        if not match:
            continue
        if match.group("rest"):
            rest_start = line.content_start + match.start("rest")
            rng = name_like_range(text, rest_start, rest_start + len(match.group("rest")))
            if rng:
                found.append(rng)
            continue
        following = [ln for ln in lines[index + 1 : index + 3] if not ln.is_blank]
        if following:
            nxt = following[0]
            rng = name_like_range(text, nxt.content_start, nxt.end)
            if rng:
                found.append(rng)
    return found


def signature_blocks(text: str) -> list[tuple[int, int]]:
    """Character ranges of signature blocks.

    A block starts at a closing line and runs until the first blank line
    after the name, the start of a quoted earlier message, or the end of text.
    """
    blocks: list[tuple[int, int]] = []
    lines = split_lines(text)
    for index, line in enumerate(lines):
        match = _CLOSING_RE.match(line.content)
        if not match:
            continue
        if match.group("rest"):
            rest_start = line.content_start + match.start("rest")
            if not name_like_range(text, rest_start, rest_start + len(match.group("rest"))):
                continue
        end = line.end
        seen_content = bool(match.group("rest"))
        for nxt in lines[index + 1 :]:
            if nxt.is_blank:
                if seen_content:
                    break
                continue
            if _QUOTE_HEADER_RE.match(nxt.content):
                break
            seen_content = True
            end = nxt.end
        blocks.append((line.start, end))
    return blocks


def name_email_pairs(text: str) -> list[tuple[tuple[int, int], tuple[int, int], str]]:
    """("Display Name" range, address range, address) for each "Name <address>"."""
    pairs = []
    for match in _NAME_EMAIL_RE.finditer(text):
        name = match.group("name").strip()
        if not name:
            continue
        name_start = match.start("name")
        pairs.append(((name_start, name_start + len(name)), match.span("email"), match.group("email")))
    return pairs


def wrote_line_names(text: str) -> list[tuple[int, int]]:
    """Author names in reply headers such as "On 12.03.2026 Lucia Benková wrote:"."""
    found = []
    for line in split_lines(text):
        match = _WROTE_RE.match(line.content)
        if match:
            start = line.content_start + match.start("name")
            found.append((start, start + len(match.group("name"))))
    return found


_SENTENCE_END_RE = re.compile(r"[.!?]+(?=\s|$)|\n")


def top_message_end(text: str) -> int:
    """End of the newest message: the start of the first quoted earlier message."""
    for line in split_lines(text):
        if line.content.startswith(">") or _QUOTE_HEADER_RE.match(line.content):
            if not line.content.startswith("From:") or line.start > 0:
                return line.start
    return len(text)


def sentence_ranges(text: str, start: int = 0, end: int | None = None) -> list[tuple[int, int]]:
    """Split [start, end) at sentence punctuation followed by space, and at newlines."""
    end = len(text) if end is None else end
    ranges = []
    pos = start
    for match in _SENTENCE_END_RE.finditer(text, start, end):
        if text[pos : match.start()].strip():
            ranges.append((pos, match.end()))
        pos = match.end()
    if text[pos:end].strip():
        ranges.append((pos, end))
    return ranges


def is_first_person(text: str) -> bool:
    """True if the text contains a first-person word (I, my, our, som, мені ...)."""
    return any(word.group().casefold() in lexicon.FIRST_PERSON_WORDS for word in _WORD_RE.finditer(text))


def self_intro_ranges(text: str, include_here: bool = False) -> list[tuple[int, int]]:
    """Ranges after "I'm", "my name is", "this is", ... (and "<Name> here")."""
    found = []
    patterns = [_SELF_INTRO_RE] + ([_HERE_RE] if include_here else [])
    for pattern in patterns:
        for match in pattern.finditer(text):
            words = list(_WORD_RE.finditer(text, *match.span("name")))
            kept = []
            for word in words:
                if not is_capitalized(word.group()) or word.group().casefold() in lexicon.STOPWORDS:
                    break
                kept.append(word)
            if kept:
                found.append((kept[0].start(), kept[-1].end()))
    return sorted(set(found))
