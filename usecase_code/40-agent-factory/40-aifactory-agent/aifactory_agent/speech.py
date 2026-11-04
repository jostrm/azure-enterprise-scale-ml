"""Turn a Markdown answer into text that is pleasant to hear.

The on-screen answer stays the authoritative, fully cited rendition. Speech is a shorter, faithful rendition:
citations markers, code, tables and links are not read aloud (their presence is announced instead), identifiers
are split so speech does not spell them out, and long answers stop at a sentence boundary.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

TRUNCATION_SUFFIX = "The full answer is on screen."
MIN_CHARACTERS = 100

_CITATION = re.compile(r"\s*\[[SGA]\d+\]")
_IMAGE = re.compile(r"!\[([^\]]*)\]\([^)]*\)")
_LINK = re.compile(r"\[([^\]]+)\]\([^)]*\)")
_URL = re.compile(r"https?://[^\s)>\]]+")
_TAG = re.compile(r"<[^>]+>")
_INLINE_CODE = re.compile(r"`([^`]+)`")
_BOLD = re.compile(r"(\*\*|__)(.+?)\1")
_STRIKE = re.compile(r"~~(.+?)~~")
_STAR_EMPHASIS = re.compile(r"\*([^*\n]+)\*")
_UNDERSCORE_EMPHASIS = re.compile(r"(?<!\w)_([^_\n]+)_(?!\w)")
_INNER_UNDERSCORE = re.compile(r"(?<=\w)_(?=\w)")
_IDENTIFIER = re.compile(r"[A-Za-z][A-Za-z0-9]{7,}")
_CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")
_HEADING = re.compile(r"^#{1,6}\s+")
_QUOTE = re.compile(r"^>\s?")
_LIST_MARKER = re.compile(r"^(?:[-*+\u2022]|\d{1,3}[.)])\s+")
_TABLE_ROW = re.compile(r"^\|")
_TABLE_RULE = re.compile(r"^[-:| ]{3,}$")
_SENTENCE_END = re.compile(r"[.!?\u2026](?=\s|$)")
_SPACE_BEFORE_PUNCTUATION = re.compile(r"\s+([.,;:!?])")
_DANGLING = re.compile(r"([:;,])\s*\.(?=\s|$)")
_TERMINAL = (".", "!", "?", ":", "\u2026")

_LABELS = {"code": ("the code", False), "table": ("the table", False), "link": ("the links", True)}


@dataclass(frozen=True)
class SpokenText:
    text: str
    truncated: bool = False
    omitted: tuple[str, ...] = ()


def _split_identifiers(line: str) -> str:
    line = _INNER_UNDERSCORE.sub(" ", line)

    def split(match: re.Match) -> str:
        token = match.group(0)
        if len(_CAMEL_BOUNDARY.findall(token)) < 2:
            return token
        return _CAMEL_BOUNDARY.sub(" ", token)

    return _IDENTIFIER.sub(split, line)


def _clean_line(line: str, omitted: list[str]) -> str:
    line = _CITATION.sub("", line)
    line = _IMAGE.sub(r"\1", line)
    line = _LINK.sub(r"\1", line)
    if _URL.search(line):
        if "link" not in omitted:
            omitted.append("link")
        line = _URL.sub("", line)
    line = _TAG.sub("", line)
    line = _INLINE_CODE.sub(r"\1", line)
    line = _BOLD.sub(r"\2", line)
    line = _STRIKE.sub(r"\1", line)
    line = _STAR_EMPHASIS.sub(r"\1", line)
    line = _UNDERSCORE_EMPHASIS.sub(r"\1", line)
    line = _split_identifiers(line)
    line = re.sub(r"\s+", " ", line).strip()
    line = _SPACE_BEFORE_PUNCTUATION.sub(r"\1", line)
    return _DANGLING.sub(r"\1", line).strip()


def _omitted_sentence(omitted: tuple[str, ...]) -> str:
    names = [_LABELS[kind][0] for kind in omitted]
    plural = len(names) > 1 or any(_LABELS[kind][1] for kind in omitted)
    joined = names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]
    return f"{joined[0].upper()}{joined[1:]} {'are' if plural else 'is'} on screen."


def _truncate(text: str, budget: int) -> str:
    candidate = text[:budget]
    ends = list(_SENTENCE_END.finditer(candidate))
    if ends:
        return candidate[:ends[-1].end()]
    space = candidate.rfind(" ")
    cut = (candidate[:space] if space > 0 else candidate).rstrip(" ,;:-")
    return cut + "."


def spoken_text(text: str, *, max_chars: int = 1200) -> SpokenText:
    if max_chars < MIN_CHARACTERS:
        raise ValueError(f"max_chars must be at least {MIN_CHARACTERS}.")
    omitted: list[str] = []
    sentences: list[str] = []
    in_code = False
    for raw in (text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        stripped = raw.strip()
        if stripped.startswith(("```", "~~~")):
            if not in_code and "code" not in omitted:
                omitted.append("code")
            in_code = not in_code
            continue
        if in_code or not stripped:
            continue
        if _TABLE_ROW.match(stripped) or _TABLE_RULE.match(stripped):
            if "table" not in omitted:
                omitted.append("table")
            continue
        structural = False
        if _HEADING.match(stripped):
            stripped, structural = _HEADING.sub("", stripped), True
        stripped = _QUOTE.sub("", stripped)
        if _LIST_MARKER.match(stripped):
            stripped, structural = _LIST_MARKER.sub("", stripped), True
        line = _clean_line(stripped, omitted)
        if not line:
            continue
        if structural and not line.endswith(_TERMINAL):
            line += "."
        sentences.append(line)
    body = " ".join(sentences)
    omitted_kinds = tuple(omitted)
    suffix = _omitted_sentence(omitted_kinds) if omitted_kinds else ""
    if not suffix:
        if len(body) <= max_chars:
            return SpokenText(body)
    elif len(body) + (1 if body else 0) + len(suffix) <= max_chars:
        return SpokenText(f"{body} {suffix}".strip(), False, omitted_kinds)
    budget = max_chars - len(TRUNCATION_SUFFIX) - 1
    return SpokenText(f"{_truncate(body, budget)} {TRUNCATION_SUFFIX}".strip(), True, omitted_kinds)
