"""
The registry behind the BIST ownership board, and the rule that ties a
shareholder row to an entity.

The matcher is the one place this board can lie by merging two holders into
one, so what is pinned is where it refuses: a short row must match exactly, a
clipped row may prefix-match but only when one entity could own it, and a
spelling two entities both claim goes to neither.
"""

import json
import os

import pytest

from services.bist.ownership import registry
from services.bist.ownership.registry import AliasIndex, EntityConfig, normalise_holder


def _entity(entity_id: str, *aliases: str, category: str = "holding") -> EntityConfig:
    return EntityConfig(
        id=entity_id,
        name=entity_id,
        category=category,
        aliases=tuple(aliases),
        sources={"shareholders": {}},
    )


class TestNormalise:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("Koç Holding Anonim Şirketi", "koç holding"),
            ("Koç Holding A.Ş.", "koç holding"),
            ("Koç Finansal Hizmetler Aş", "koç finansal hizmetler"),
            # The fifty-character cut leaves a fragment of the suffix behind.
            (
                "Merkez Bereket Gıda Sanayi Ve Ticaret Anonim Şirke",
                "merkez bereket gıda sanayi ve ticaret",
            ),
            (
                "Family Danışmanlık Gayrimenkul Ve Ticaret Anonim Ş",
                "family danışmanlık gayrimenkul ve ticaret",
            ),
            # Dotted and dotless I fold the Turkish way, and title-cased foreign
            # names with dotless ı land on the same key as their ASCII spelling
            # only when the registry spells them the way the card does.
            ("Türkiye Iş Bankası A.Ş.", "türkiye ış bankası"),
            ("TÜRKİYE İŞ BANKASI A.Ş.", "türkiye iş bankası"),
        ],
    )
    def test_folds_and_strips_the_corporate_suffix(self, raw, expected):
        assert normalise_holder(raw) == expected


class TestAliasIndex:
    def test_exact_match_on_the_folded_form(self):
        index = AliasIndex([_entity("koc", "Koç Holding Anonim Şirketi")])

        assert index.match("KOÇ HOLDİNG A.Ş.") == "koc"
        assert index.match("Koç Holding Anonim Şirketi") == "koc"

    def test_a_short_row_never_prefix_matches(self):
        index = AliasIndex([_entity("koc", "Koç Holding Anonim Şirketi")])

        # "Koç" is a prefix of the alias, and is also every other Koç company.
        assert index.match("Koç") is None
        assert index.match("Koç Finansal Hizmetler Aş") is None

    def test_a_clipped_row_matches_the_alias_it_is_a_prefix_of(self):
        full = "TVF Bilgi Teknolojileri İletişim Hizmetleri Yatırım Sanayi ve Ticaret A.Ş."
        index = AliasIndex([_entity("tvf", full)])
        clipped = "TVF Bilgi Teknolojileri İletişim Hizmetleri Yatırı"
        assert len(clipped) == 50

        assert index.match(clipped) == "tvf"

    def test_a_clipped_row_two_entities_could_own_goes_to_neither(self):
        index = AliasIndex(
            [
                _entity("a", "Anadolu Yatırım Holding Gayrimenkul Ve Ticaret Anonim Şirketi Alpha"),
                _entity("b", "Anadolu Yatırım Holding Gayrimenkul Ve Ticaret Anonim Şirketi Beta"),
            ]
        )
        clipped = "Anadolu Yatırım Holding Gayrimenkul Ve Ticaret Ano"
        assert len(clipped) == 50

        assert index.match(clipped) is None

    def test_a_spelling_two_entities_claim_goes_to_neither(self):
        index = AliasIndex([_entity("a", "Esas Holding A.Ş."), _entity("b", "Esas Holding")])

        assert index.match("Esas Holding A.Ş.") is None


class TestLoadEntities:
    @pytest.fixture
    def registry_file(self, tmp_path, monkeypatch):
        path = os.path.join(tmp_path, "entities.json")
        monkeypatch.setattr(registry, "ENTITIES_FILE", path)

        def write(rows):
            with open(path, "w", encoding="utf-8") as fh:
                json.dump({"version": 1, "entities": rows}, fh)

        return write

    def test_drops_rows_that_cannot_be_trusted(self, registry_file):
        registry_file(
            [
                {
                    "id": "ok",
                    "name": "OK",
                    "category": "holding",
                    "aliases": ["OK A.Ş."],
                    "sources": {"shareholders": {}},
                },
                {
                    "id": "no-alias",
                    "name": "X",
                    "category": "holding",
                    "sources": {"shareholders": {}},
                },
                {
                    "id": "bad-cat",
                    "name": "X",
                    "category": "politician",
                    "aliases": ["X"],
                    "sources": {"shareholders": {}},
                },
                {"id": "no-source", "name": "X", "category": "holding", "aliases": ["X"]},
                {
                    "id": "fund-no-code",
                    "name": "X",
                    "category": "fund",
                    "sources": {"kap_fund": {}},
                },
                {
                    "id": "fund",
                    "name": "F",
                    "category": "fund",
                    "order": 5,
                    "sources": {"kap_fund": {"code": "ak3"}},
                },
                "not a row",
            ]
        )

        loaded = registry.load_entities()

        assert [e.id for e in loaded] == ["fund", "ok"]
        assert loaded[0].fund_code == "AK3"
        assert loaded[0].fund_type == "YAT"
        assert not loaded[0].tracks_shareholders
        assert loaded[1].tracks_shareholders

    def test_a_missing_file_is_an_empty_registry(self, registry_file):
        assert registry.load_entities() == []

    def test_the_shipped_registry_loads_and_every_alias_is_unambiguous(self, monkeypatch):
        monkeypatch.undo()
        entities = registry.load_entities()
        assert len(entities) >= 20

        index = AliasIndex(entities)
        for entity in entities:
            for alias in entity.aliases:
                assert index.match(alias) == entity.id, alias
