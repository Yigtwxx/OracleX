"""
TEFAS's fifty-four portfolio lines, collapsed into something a bar can say.

TEFAS publishes a fund's split across 54 instrument codes. Drawn literally that
is 54 segments, most of them a hair wide, and a reader learns nothing from it.
Drawn as a dozen buckets it answers the question the bar exists for: is this an
equity fund, a bond fund, or a money-market fund wearing a different name.

**The rule that decides every bucket:** group by economic exposure where the
field names it, and by wrapper where the wrapper is all the field names. A gold
participation account tracks the gold price, not a bank's deposit rate, so it is
a precious metal and not a deposit — a katılım gold fund holds almost nothing
else, and filing it under deposits would draw it as a money-market fund. A real
estate investment fund's units are real estate. But a plain `yyf` participation
unit could hold anything at all, so "fund units" *is* the honest label.

Two judgement calls that could reasonably go the other way, recorded so they are
argued with rather than rediscovered:

* `eut` (Eurobonds) sits under public debt. Most of the Turkish eurobond float
  is sovereign; corporate issues exist and land in the wrong bucket. Giving them
  their own bucket would spend a thirteenth colour on a rounding error.
* `ymk` (Yabancı Menkul Kıymet) sits under foreign debt. The code is generic,
  but `yhs` already carries foreign equity, so `ymk` is what is left.

Pure: no I/O, no cache, no clock. `fund_service` owns all three.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from services.bist.tefas_client import ALLOCATION_FIELDS

# Where an unmapped field goes. TEFAS added codes in the 2026 rewrite and will
# again; dropping an unknown one would quietly shrink the bar and leave the
# reported total unexplained.
UNKNOWN_BUCKET = "diger"

# Bar order, and deliberately also the adjacency plan: because the order is
# fixed, the pairs that can ever touch are fixed too. Gold and amber are the
# only two fills close in hue and they sit six positions apart, so no bar can
# put them side by side. See `frontend/lib/fund-allocation.ts` for the colours.
BUCKET_ORDER: tuple[str, ...] = (
    "hisse",
    "yabanci_hisse",
    "gayrimenkul",
    "fon",
    "kiymetli_maden",
    "ozel_borclanma",
    "kamu_borclanma",
    "yabanci_borclanma",
    "mevduat",
    "para_piyasasi",
    "turev",
    UNKNOWN_BUCKET,
)

BUCKET_LABELS: dict[str, str] = {
    "hisse": "Hisse senedi",
    "yabanci_hisse": "Yabancı hisse senedi",
    "gayrimenkul": "Gayrimenkul ve girişim",
    "fon": "Fon katılma payları",
    "kiymetli_maden": "Kıymetli madenler",
    "ozel_borclanma": "Özel sektör borçlanma",
    "kamu_borclanma": "Kamu borçlanma",
    "yabanci_borclanma": "Yabancı borçlanma",
    "mevduat": "Mevduat ve katılma hesabı",
    "para_piyasasi": "Repo ve para piyasası",
    "turev": "Türev ve teminat",
    UNKNOWN_BUCKET: "Diğer",
}

_BUCKET_FIELDS: dict[str, tuple[str, ...]] = {
    "hisse": ("hs",),
    "yabanci_hisse": ("yhs",),
    # Unit trusts included: a GYF or GSYF unit is real estate or venture by
    # definition, where a plain fund unit is not.
    "gayrimenkul": ("gas", "gyy", "gsyy", "gykb", "gsykb"),
    "fon": ("yyf", "byf", "ybyf", "fkb"),
    # `khau`/`vmau` are gold accounts and belong to the metal, not to the bank
    # holding it — see the module docstring.
    "kiymetli_maden": ("km", "kmbyf", "kmkba", "kmkks", "khau", "vmau"),
    "ozel_borclanma": ("ost", "fb", "bb", "vdm", "osdb", "osks", "oksyd"),
    "kamu_borclanma": (
        "dt",
        "hb",
        "kibd",
        "kba",
        "kkstl",
        "kksd",
        "kksyd",
        "kks",
        "eut",
        "db",
        "dot",
    ),
    "yabanci_borclanma": ("ybkb", "ybosb", "yba", "ymk"),
    "mevduat": ("vmtl", "vmd", "vm", "khtl", "khd", "kh"),
    "para_piyasasi": ("bpp", "tpp", "r", "tr", "btaa", "btas"),
    "turev": ("t", "vint"),
    UNKNOWN_BUCKET: ("d",),
}

FIELD_BUCKETS: dict[str, str] = {
    field: bucket for bucket, fields in _BUCKET_FIELDS.items() for field in fields
}


@dataclass(frozen=True)
class AllocationLine:
    """One TEFAS instrument line inside a bucket."""

    code: str
    label: str
    weight: float


@dataclass(frozen=True)
class AllocationBucket:
    key: str
    label: str
    weight: float
    lines: tuple[AllocationLine, ...]
    """Largest first. One line means the bucket *is* that line."""


@dataclass(frozen=True)
class AllocationBreakdown:
    """One fund's split, grouped and ready to draw."""

    day: date
    total: float
    """
    Everything TEFAS reported, summed. **Never normalised to 1.**

    Rows land near 1 but rarely on it. Scaling the segments up to fill the bar
    would invent the missing sliver; leaving the remainder as bare track and
    printing the real total lets the page say what it actually knows.
    """
    buckets: tuple[AllocationBucket, ...]
    """In `BUCKET_ORDER`, not by size — a fixed order is what lets two funds'
    bars be read against each other, which is the whole point of the column."""


def group_allocation(weights: dict[str, float], day: date) -> AllocationBreakdown | None:
    """
    Collapse one fund's reported lines into buckets.

    Returns None for a fund with nothing reported. An empty breakdown would draw
    a zero-length bar, and a zero-length bar reads as "this fund holds nothing" —
    a claim, where the truth is that TEFAS published no claim at all.
    """
    if not weights:
        return None

    grouped: dict[str, list[AllocationLine]] = {}
    for code, weight in weights.items():
        if weight <= 0:
            continue
        bucket = FIELD_BUCKETS.get(code, UNKNOWN_BUCKET)
        label = ALLOCATION_FIELDS.get(code, code)
        grouped.setdefault(bucket, []).append(AllocationLine(code=code, label=label, weight=weight))

    if not grouped:
        return None

    buckets: list[AllocationBucket] = []
    for key in BUCKET_ORDER:
        lines = grouped.get(key)
        if not lines:
            continue
        lines.sort(key=lambda line: line.weight, reverse=True)
        buckets.append(
            AllocationBucket(
                key=key,
                label=BUCKET_LABELS[key],
                weight=sum(line.weight for line in lines),
                lines=tuple(lines),
            )
        )

    return AllocationBreakdown(
        day=day,
        total=sum(bucket.weight for bucket in buckets),
        buckets=tuple(buckets),
    )


def bucket_weights(breakdown: AllocationBreakdown) -> dict[str, float]:
    """
    The screener row's form: bucket key to weight, absent meaning not held.

    Sparse and unlabelled on purpose. The board carries this for every fund on
    it, and repeating a dozen Turkish labels thirteen hundred times to say the
    same thing the vocabulary in the response meta already says is most of the
    payload.
    """
    return {bucket.key: bucket.weight for bucket in breakdown.buckets}


def bucket_vocabulary() -> list[dict[str, str]]:
    """The key-to-label table, sent once on the board rather than per row."""
    return [{"key": key, "label": BUCKET_LABELS[key]} for key in BUCKET_ORDER]
