"""
The band drawn on every KAP row.

This is the one classifier on the realm that runs on all sixty rows of a live
tape, so it is also the one whose mistakes a reader sees sixty at a time. Three
kinds of test, and the third is the load-bearing one:

* **The forms classify.** KAP titles are enumerated template names, which is the
  whole reason a phrase table is close to ground truth here rather than a
  heuristic.
* **Order resolves the pairs that overlap.** A report about a capital increase
  is not a capital increase; an injunction is not a circuit breaker. Both were
  wrong before the rules were ordered, and neither is visible in review.
* **A filing whose title says nothing gets no band.** "Rutin" on a merger is
  worse than nothing at all, which is the same rule `/api/price` follows when it
  404s a symbol it cannot resolve.
"""

import pytest

from services.bist.kap_materiality import (
    _RULES,
    BAND_HIGH,
    BAND_MEDIUM,
    BAND_ROUTINE,
    BAND_UNCLASSIFIED,
    MAX_SCORE,
    MIN_SCORE,
    SCORE_HIGH,
    SCORE_MEDIUM,
    band_for_score,
    classify,
)


@pytest.mark.parametrize(
    "title,band",
    [
        # The forms as KAP actually files them, copied from a live tape.
        ("Sermaye Artırımı - Azaltımı İşlemlerine İlişkin Bildirim", BAND_HIGH),
        ("Payların Geri Alınmasına İlişkin Bildirim", BAND_HIGH),
        ("Kar Payı Dağıtım İşlemlerine İlişkin Bildirim", BAND_HIGH),
        ("Bölünme İşlemlerine İlişkin Bildirim", BAND_HIGH),
        ("Pay Alım Teklifi Yoluyla Pay Toplanmasına İlişkin Bildirim", BAND_HIGH),
        ("Endeks Şirketlerinde Değişiklik", BAND_HIGH),
        ("Ortaklık Aleyhine Dava Açılması veya Davaya İlişkin Gelişmeler", BAND_HIGH),
        ("İzahname", BAND_HIGH),
        ("Yeni İş İlişkisi", BAND_MEDIUM),
        ("Kredi Derecelendirmesi", BAND_MEDIUM),
        ("Genel Kurul İşlemlerine İlişkin Bildirim", BAND_MEDIUM),
        ("Haber ve Söylentilere İlişkin Açıklama", BAND_MEDIUM),
        ("Bağımsız Denetim Kuruluşunun Belirlenmesi", BAND_MEDIUM),
        ("Pay Alım Satım Bildirimi", BAND_MEDIUM),
        ("İhraç Tavanına İlişkin Bildirim", BAND_MEDIUM),
        ("Pay Bazında Devre Kesici Bildirimi", BAND_ROUTINE),
        ("Fon Sürekli Bilgilendirme Formu", BAND_ROUTINE),
        ("Borsa Dışı Repo - Ters Repo Sözleşmesi", BAND_ROUTINE),
        ("Şirket Genel Bilgi Formu", BAND_ROUTINE),
        ("Takasbank Para Piyasası Günlük Bülten", BAND_ROUTINE),
        ("Piyasa Yapıcılığı Kapsamında Gerçekleştirilen İşlemler Bildirimi", BAND_ROUTINE),
    ],
)
def test_the_standard_forms_classify(title, band):
    assert classify(title).band == band


def test_a_report_about_a_capital_increase_is_not_a_capital_increase():
    """
    The pair the rule order exists for.

    "Sermaye Artırımından Elde Edilen Fonun Kullanımına İlişkin Rapor" contains
    the raise's own phrase and is a progress report filed long after it. Ranked
    the other way round it lit up as a capital increase every quarter.
    """
    filing = classify("Sermaye Artırımından Elde Edilecek - Edilen Fonun Kullanımına İlişkin Rapor")
    assert filing.band == BAND_MEDIUM
    assert filing.event == "fon_kullanim_raporu"


def test_a_governance_form_is_not_a_change_of_management():
    """
    "Kurumsal Yönetim Bilgi Formu (Güncelleme)" names the board in its own
    title, so the board-change rule claimed it and a periodic form update was
    scored as a change of management on the live tape.
    """
    filing = classify("Kurumsal Yönetim Bilgi Formu (Güncelleme) - Yönetim Kurulu")
    assert filing.event == "bilgi_formu"
    assert filing.band == BAND_ROUTINE


def test_an_injunction_is_not_a_circuit_breaker():
    """`tedbir` means both "measure" and "injunction"; only one is mechanical."""
    assert classify("İhtiyati Tedbir Kararı Hakkında").event == "dava_sureci"
    assert classify("Pay Bazında Devre Kesici Bildirimi").event == "tedbir"


def test_an_acronym_folded_the_turkish_way_still_matches():
    """
    `fold` maps a dotless capital I to "ı", so "BISTECH" becomes "bıstech".

    A phrase written the way the acronym looks never matches the title it was
    written for, and the row falls through to unclassified. The rule is spelled
    without the acronym for exactly this reason.
    """
    assert classify("BISTECH Pay Piyasası Alım Satım Sistemi Duyurusu").band == BAND_ROUTINE


def test_a_financial_report_is_classified_by_its_category():
    """A report filed under a title the table does not carry is still a report."""
    filing = classify("Bilinmeyen Bir Form Adı", "", "FR")
    assert filing.band == BAND_HIGH
    assert filing.matched == "category:FR"


def test_a_free_text_form_gets_no_band_rather_than_a_low_one():
    filing = classify("Özel Durum Açıklaması (Genel)", "")
    assert filing.band == BAND_UNCLASSIFIED
    assert filing.matched == ""


def test_an_unclassified_filing_scores_none_rather_than_zero():
    """
    Zero is the bottom of the scale. This filing was never placed on it, and a
    bar drawn from a zero would rank it below the fund forms it was not compared
    against.
    """
    assert classify("Genel Açıklama", "").score is None


def test_every_rule_sits_on_the_scale():
    for event, _label, score, _phrases in _RULES:
        assert MIN_SCORE <= score <= MAX_SCORE, f"{event} scored {score}"


def test_every_rule_reaches_the_caller_with_a_band_its_score_agrees_with():
    """
    One number drives the bar and the badge, so they cannot disagree about the
    same filing — which is what an independently-set band would eventually do.

    Run through `classify` rather than against the table, so the check covers
    the path the router actually takes.
    """
    for event, _label, _score, phrases in _RULES:
        filing = classify(phrases[0])
        assert filing.event == event, f"{phrases[0]!r} was classified as {filing.event}"
        assert filing.band == band_for_score(filing.score)


def test_the_band_cuts_sit_where_the_constants_say():
    assert band_for_score(MAX_SCORE) == BAND_HIGH
    assert band_for_score(SCORE_HIGH) == BAND_HIGH
    assert band_for_score(SCORE_HIGH - 1) == BAND_MEDIUM
    assert band_for_score(SCORE_MEDIUM) == BAND_MEDIUM
    assert band_for_score(SCORE_MEDIUM - 1) == BAND_ROUTINE
    assert band_for_score(MIN_SCORE) == BAND_ROUTINE
    assert band_for_score(None) == BAND_UNCLASSIFIED


def test_the_filings_that_can_end_a_listing_top_the_scale():
    """
    Ordering, not measurement. A tender offer can take the company off the
    exchange; a buyback buys shares back. Nobody measured either, and the scale
    claims no more than that the two are not the same size.
    """
    assert classify("Pay Alım Teklifi Yoluyla Pay Toplanmasına İlişkin Bildirim").score == MAX_SCORE
    assert classify("Payların Geri Alınmasına İlişkin Bildirim").score < MAX_SCORE
    assert classify("Fon Sürekli Bilgilendirme Formu").score == MIN_SCORE


def test_a_free_text_form_is_classified_from_the_company_s_own_summary():
    filing = classify("Özel Durum Açıklaması (Genel)", "Kredi Kullanımı hakkında")
    assert filing.band == BAND_MEDIUM
    assert filing.event == "borclanma"


def test_a_named_form_outranks_its_own_body():
    """
    A capital increase whose body mentions a general meeting is a capital
    increase. Letting the body outvote a title that named the form would make
    the commonest filings the least reliably classified.
    """
    filing = classify(
        "Sermaye Artırımı - Azaltımı İşlemlerine İlişkin Bildirim",
        "Genel kurul toplantısında görüşülmek üzere.",
    )
    assert filing.event == "sermaye"


def test_every_decision_names_the_phrase_that_made_it():
    """An unauditable classifier is one nobody dares change."""
    assert classify("Kredi Derecelendirmesi").matched == "kredi derecelendirmesi"


def test_an_empty_filing_is_unclassified_rather_than_an_error():
    assert classify("", "").band == BAND_UNCLASSIFIED
