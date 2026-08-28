"""
Turkish-aware text folding.

One function, and it exists because `str.casefold` gets Turkish wrong in a way
that fails silently.

Turkish has two letters where English has one. `İ` (dotted capital) lowercases
to `i`; `I` (dotless capital) lowercases to `ı`. Unicode's locale-independent
rule cannot know which language it is looking at, so it refuses to discard the
dot: `"KESİCİ".casefold()` produces `"kesi̇ci̇"` — an ASCII `i` followed by a
combining dot above — while `"Kesici".casefold()` produces plain `"kesici"`.
The two strings look identical in a terminal and do not compare equal.

That is not a curiosity here. Borsa İstanbul files a good share of its notices
in capitals, and company names arrive in whatever case their filer typed, so
every case-insensitive comparison on this realm — the restriction radar, the
fund search, the equity search — has to fold the Turkish way or quietly miss
matches containing the commonest letter in the language.
"""

from __future__ import annotations

# Applied before `casefold` so the dot is resolved by the Turkish rule rather
# than preserved by the Unicode one.
_TURKISH_FOLD = str.maketrans({"İ": "i", "I": "ı"})


def fold(text: str) -> str:
    """Lowercase `text` for comparison, the way Turkish does it."""
    return text.translate(_TURKISH_FOLD).casefold()


def contains(haystack: str, needle: str) -> bool:
    """Case-insensitive substring test that survives Turkish capitals."""
    return fold(needle) in fold(haystack)
