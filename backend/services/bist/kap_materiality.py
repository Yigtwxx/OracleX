"""
What kind of filing this is, decided without a model.

The tape prints sixty rows and every one of them looks the same: a title, a
company, a timestamp. A reader scanning it cannot tell a capital increase from a
weekly fund form without reading each line, and the two are not close in
consequence. This module puts a class and a band on every row so the scan works.

**Why this is not the model's job.** The note in `kap_note.py` costs tens of
seconds on a local model and is written for the one filing a reader opens.
Classifying sixty rows that way would run the model continuously to label text
nobody asked about, and the answers would differ between two identical filings.
It is also the house rule: every surface on this realm computes its own label,
thresholds and bands in Python and hands the model a finished classification to
*explain* — `prompts/notes/rules.md` spells that out as "the classification
above was computed before you saw it; explain it, do not revise it".

**Why a lookup table beats anything cleverer.** KAP titles are not free prose.
They are enumerated form names — "Sermaye Artırımı - Azaltımı İşlemlerine
İlişkin Bildirim", "Kar Payı Dağıtım İşlemlerine İlişkin Bildirim" — filed from
a template, so a phrase table over the title is close to ground truth rather
than a heuristic standing in for one. Roughly nine rows in ten are named by one
of these forms.

**The tenth row is the reason `unclassified` exists.** "Özel Durum Açıklaması
(Genel)" and "Genel Açıklama" are the free-text forms, and their title says
nothing at all about what is inside. Those get no band. This realm declines
rather than guesses — a filing labelled "Rutin" that announced a merger is worse
than one labelled nothing — and an unbanded row is exactly the row the analysis
button is there for.

The band is about the *class of event*, never about a price. A capital increase
is high because it changes the share count, not because the share is predicted
to move; nothing here forecasts anything.
"""

from __future__ import annotations

from dataclasses import dataclass

from services.bist.text import fold

# The four bands. `UNCLASSIFIED` is not a fourth level of importance — it is the
# absence of a reading, and the UI must render it as such rather than as "low".
BAND_HIGH = "high"
BAND_MEDIUM = "medium"
BAND_ROUTINE = "routine"
BAND_UNCLASSIFIED = "unclassified"

# The scale a filing is scored on, and where the bands cut it.
#
# The score is the single source of truth and the band is derived from it, so a
# rule cannot be given a 9 and a "routine" badge by an edit that changes one and
# forgets the other. The cuts are where they are because the scale is about what
# the filing *touches*: at 7 and above it moves the capital, the ownership or
# the earnings; from 4 it is something a holder acts on with the capital
# unchanged; below that it is mechanical.
#
# The numbers inside a band are ordering, not measurement. A tender offer at 10
# outranks a buyback at 8 because it can end the listing while the other buys
# shares back — nobody measured either, and the scale claims no more precision
# than "these two are not the same size".
MIN_SCORE = 1
MAX_SCORE = 10
SCORE_HIGH = 7
SCORE_MEDIUM = 4


@dataclass(frozen=True)
class Materiality:
    """One filing's class, and how it was decided."""

    event: str
    """Stable key. Safe to switch on; the label is not."""
    label: str
    """Turkish, and short enough for a chip on a dense row."""
    score: int | None
    """
    1-10, or None when the filing could not be classified at all.

    None rather than 0: a zero sits at the bottom of the scale, and this is a
    filing that was never placed on it.
    """
    band: str
    """Derived from `score`. Never set independently."""
    matched: str
    """
    The phrase that decided it, or "" for an unclassified filing.

    Carried so a wrong badge can be traced to the rule that produced it without
    re-deriving the match by hand. A classifier whose decisions cannot be
    audited is one nobody dares change.
    """


# The table, in priority order: the first phrase found in the title wins.
#
# Order is load-bearing, and the pairs that make it so are worth naming.
# "Sermaye Artırımından Elde Edilecek Fonun Kullanımına İlişkin Rapor" contains
# "sermaye artırım" and is a progress report on a raise that already happened,
# not the raise — so it sits above the raise. Same shape for the prospectus that
# follows an offering and the assumptions report that precedes one.
_RULES: tuple[tuple[str, str, int, tuple[str, ...]], ...] = (
    # ── Reports *about* a corporate action, above the action itself ──────────
    (
        "fon_kullanim_raporu",
        "Fon kullanım raporu",
        4,
        ("fonun kullanımına ilişkin rapor",),
    ),
    (
        "halka_arz_degerlendirme",
        "Halka arz değerlendirmesi",
        5,
        ("halka arz fiyatının belirlenmesinde",),
    ),
    (
        # Above `yonetim`, and the third pair in this group: a governance form
        # names the board in its own title, so the board-change rule claimed it
        # and a periodic form update was scored as a change of management.
        "bilgi_formu",
        "Bilgi formu",
        2,
        ("kurumsal yönetim bilgi formu", "bilgi formu (güncelleme)"),
    ),
    # ── Capital, ownership and earnings: the filings that change the company ──
    (
        "sermaye",
        "Sermaye artırımı/azaltımı",
        9,
        ("sermaye artırımı", "sermaye azaltımı", "bedelli", "bedelsiz"),
    ),
    (
        "geri_alim",
        "Pay geri alımı",
        8,
        ("payların geri alınması", "pay geri alım", "geri alım programı"),
    ),
    (
        "temettu",
        "Kâr payı",
        8,
        ("kar payı dağıtım", "kâr payı dağıtım", "temettü"),
    ),
    (
        "birlesme",
        "Birleşme/bölünme",
        10,
        ("birleşme işlemlerine", "bölünme işlemlerine", "devralma", "tür değişikliği"),
    ),
    (
        "pay_alim_teklifi",
        "Pay alım teklifi",
        10,
        (
            "pay alım teklifi",
            "çağrı yoluyla pay",
        ),
    ),
    (
        "halka_arz",
        "Halka arz",
        8,
        ("halka arz", "izahname"),
    ),
    (
        "satin_alma",
        "Şirket alım/satımı",
        9,
        (
            "şirket satın alma",
            "iştirak edinimi",
            "pay devri",
            "hisse devri",
            "ortaklık payı satışı",
            "transfer görüşmelerinin sonuçlanması",
        ),
    ),
    (
        "finansal_rapor",
        "Finansal rapor",
        9,
        ("finansal rapor", "finansal tablo", "mali tablo"),
    ),
    (
        "endeks",
        "Endeks değişikliği",
        8,
        ("endeks şirketlerinde değişiklik", "endekslerde değişiklik"),
    ),
    (
        "hukuki",
        "Hukuki gelişme",
        9,
        (
            "aleyhine dava",
            "davaya ilişkin gelişmeler",
            "konkordato",
            "iflas",
            "faaliyetlerin durdurulması",
            "idari para cezası",
        ),
    ),
    (
        # Above `tedbir` on purpose: an "ihtiyati tedbir" is an injunction, and
        # the measures rule below would otherwise file a court order under
        # circuit breakers on the strength of the shared word.
        "dava_sureci",
        "Dava süreci",
        5,
        ("ihtiyati tedbir", "mahkeme", "istinaf", "yargıtay", "dava dilekçesi"),
    ),
    # ── Filings a holder acts on, without changing the capital ───────────────
    (
        "is_iliskisi",
        "Yeni iş/sözleşme",
        6,
        ("yeni iş ilişkisi", "ihale", "sözleşme imzalan", "yatırım kararı", "kapasite artırımı"),
    ),
    (
        "derecelendirme",
        "Derecelendirme",
        6,
        ("kredi derecelendirmesi", "derecelendirme notu"),
    ),
    (
        "soylenti",
        "Söylenti açıklaması",
        6,
        ("haber ve söylentilere",),
    ),
    (
        "icsel_islem",
        "İçeriden pay işlemi",
        6,
        ("pay alım satım bildirimi", "toptan alış satış", "yönetim kurulu üyeleri ve"),
    ),
    (
        "borclanma",
        "Borçlanma aracı",
        5,
        (
            "ihraç tavanına",
            "ihraç belgesi",
            "borçlanma araçları",
            "kira sertifika",
            "tahvil",
            "kredi kullanımı",
            "kredi sözleşmesi",
        ),
    ),
    (
        "yonetim",
        "Yönetim/denetim değişikliği",
        5,
        (
            "yönetim kurulu",
            "genel müdür",
            "bağımsız denetim kuruluşunun belirlenmesi",
            "esas sözleşme",
        ),
    ),
    (
        "genel_kurul",
        "Genel kurul",
        4,
        ("genel kurul",),
    ),
    (
        "hak_kullanim",
        "Hak kullanımı",
        5,
        ("hak kullanımı", "mali hak kullanım"),
    ),
    (
        "faaliyet_raporu",
        "Faaliyet raporu",
        5,
        ("faaliyet raporu",),
    ),
    # ── Mechanical filings: real, and not company news ───────────────────────
    (
        "tedbir",
        "Tedbir/devre kesici",
        3,
        (
            "devre kesici",
            "tedbir",
            "açığa satış",
            "brüt takas",
            "kredili işlem",
            "işlem sırası",
            "sıra kapatma",
            "fiyat limiti",
            "işlem iptali",
        ),
    ),
    (
        "fon_islemi",
        "Fon işlemi",
        1,
        (
            "fon sürekli bilgilendirme",
            "borsa dışı repo",
            "borsa dışı vaad",
            "yatırımcı bilgi formu",
            "iç tüzük",
            "tanıtım formu",
            "risk ölçüm",
            "katılım finansı",
            "fon ihraç",
            "fon ünvan",
            "yatırımcı raporu",
        ),
    ),
    (
        "piyasa_islemi",
        "Piyasa işlemi",
        2,
        (
            "piyasa yapıcılığı",
            "likidite sağlayıcılık",
            "varant",
            "sertifika",
            "takasbank",
            "para piyasası",
            "ödünç pay",
            "tipe dönüşüm",
            # Spelled without the acronym: `fold` maps a dotless capital I to
            # "ı" the Turkish way, so "BISTECH" folds to "bıstech" and a phrase
            # written "bistech" never matches the title it was written for.
            "pay piyasası alım satım sistemi",
            "merkezi kayıt kuruluşu",
            "pay dışında sermaye piyasası aracı",
        ),
    ),
    (
        "bilgi_formu",
        "Bilgi formu",
        2,
        (
            "genel bilgi formu",
            "haftalık rapor",
            "sorumluluk beyanı",
            "sürdürülebilirlik",
            "yatırımcı sunumu",
            "bilgilendirme politikası",
        ),
    ),
)

# The free-text forms. Their title is a form name and says nothing about the
# filing, so a title match on them would be a match on the wrong text.
_FREE_TEXT_TITLES = (
    "özel durum açıklaması (genel)",
    "genel açıklama",
    "özel durum açıklaması",
)

UNCLASSIFIED = Materiality(
    event="serbest_metin",
    label="Serbest metin",
    score=None,
    band=BAND_UNCLASSIFIED,
    matched="",
)


def band_for_score(score: int | None) -> str:
    """
    The band a score falls in.

    Derived rather than declared, so the badge and the bar can never disagree
    about the same filing — there is one number, and everything the board draws
    comes off it.
    """
    if score is None:
        return BAND_UNCLASSIFIED
    if score >= SCORE_HIGH:
        return BAND_HIGH
    return BAND_MEDIUM if score >= SCORE_MEDIUM else BAND_ROUTINE


def _match(text: str) -> Materiality | None:
    haystack = fold(text)
    for event, label, score, phrases in _RULES:
        for phrase in phrases:
            if fold(phrase) in haystack:
                return Materiality(
                    event=event,
                    label=label,
                    score=score,
                    band=band_for_score(score),
                    matched=phrase,
                )
    return None


def classify(
    title: str,
    summary: str = "",
    category: str = "",
) -> Materiality:
    """
    The class of one filing, from its title and — where the title is a free-text
    form — from the company's own summary.

    Reading the summary only as a fallback is deliberate. A capital increase
    notice whose body happens to mention a general meeting is a capital
    increase; letting the body outvote a title that named the form would make
    the commonest filings the least reliably classified.
    """
    if category.upper() == "FR":
        # The category is the classification here. A financial report filed
        # under a title this table does not carry is still a financial report.
        return Materiality(
            event="finansal_rapor",
            label="Finansal rapor",
            score=9,
            band=BAND_HIGH,
            matched="category:FR",
        )

    by_title = _match(title)
    folded_title = fold(title)
    is_free_text = any(fold(name) == folded_title for name in _FREE_TEXT_TITLES)

    # A form name that the table recognises wins outright, unless the form is
    # one of the free-text ones — those carry no information in the title at all.
    if by_title and not is_free_text:
        return by_title

    if summary:
        by_summary = _match(summary)
        if by_summary:
            return by_summary

    return by_title or UNCLASSIFIED
