"""
The hand-maintained list of holders behind the BIST ownership board, and the
rule that ties a shareholder row to one of them.

**Curated, not derived.** Every ≥5% holder across the XU100 could be turned into
an entity automatically, and the first version was going to be. It was not
built that way because the same holder arrives under several spellings —
`Koç Holding Anonim Şirketi`, `Koç Holding A.Ş.`, a form clipped at fifty
characters — and the merge rule that reconciles them is exactly the place a
board like this tells a reader that Sabancı holds what OYAK holds. So the
registry names the entity and lists the spellings, the matcher does equality
on a folded form and nothing cleverer, and a row that matches nothing stays on
the company's page as an untracked holder rather than becoming a card.

**Matching.** Both sides are folded the Turkish way (`services.bist.text`),
stripped of the corporate suffix (`Anonim Şirketi`, `A.Ş.`, and the clipped
fragments of it the fifty-character cut leaves behind), stripped of
punctuation and collapsed to single spaces. Equal means matched. A row at the
clipping limit may also match an alias it is a prefix of — that is the one
concession to the source's truncation, and it is why the limit is a constant
here rather than a guess in the matcher.
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from typing import Any

from services.asset_registry import REGISTRY_DIR, read_json_cache
from services.bist.text import fold

logger = logging.getLogger(__name__)

ENTITIES_FILE = os.path.join(REGISTRY_DIR, "bist_ownership_entities.json")

VALID_CATEGORIES = frozenset({"holding", "state", "foreign", "fund", "other"})
VALID_SOURCES = frozenset({"shareholders", "kap_fund"})

# İş Yatırım clips holder names at this length. A row this long is assumed
# clipped and may prefix-match an alias; a shorter one must match exactly.
CLIP_LENGTH = 50

# The corporate suffix in every form the clipping can leave it — from the full
# `Anonim Şirketi` down to a lone `Anonim Ş`, plus the abbreviations. Applied
# after folding, so it is spelled in lowercase Turkish.
_COMPANY_SUFFIX = re.compile(
    r"\s+(?:anonim(?:\s+(?:şirketi|şirket|şirke|şirk|şir|şi|ş))?|a\.?ş\.?|a\.?s\.?)\s*$"
)
_PUNCTUATION = re.compile(r"[^\w\s]", re.UNICODE)
_SPACES = re.compile(r"\s+")


@dataclass(frozen=True)
class EntityConfig:
    id: str
    name: str
    category: str
    subtitle: str | None = None
    order: int = 1_000
    coverage_note: str | None = None
    aliases: tuple[str, ...] = ()
    sources: dict[str, dict[str, Any]] = field(default_factory=dict)

    @property
    def tracks_shareholders(self) -> bool:
        return "shareholders" in self.sources

    @property
    def fund_code(self) -> str | None:
        fund = self.sources.get("kap_fund")
        if not fund:
            return None
        code = fund.get("code")
        return str(code).strip().upper() if code else None

    @property
    def fund_type(self) -> str:
        fund = self.sources.get("kap_fund") or {}
        return str(fund.get("fund_type") or "YAT")


def normalise_holder(name: str) -> str:
    """The comparison form of a holder name. Deterministic and lossy on purpose."""
    text = fold(name.strip())
    text = _COMPANY_SUFFIX.sub("", text)
    text = _PUNCTUATION.sub(" ", text)
    return _SPACES.sub(" ", text).strip()


def _coerce_entity(raw: Any) -> EntityConfig | None:
    if not isinstance(raw, dict):
        return None
    entity_id = raw.get("id")
    name = raw.get("name")
    category = raw.get("category")
    if not isinstance(entity_id, str) or not entity_id:
        logger.warning("BIST ownership registry: row without an id — skipped")
        return None
    if not isinstance(name, str) or not name:
        logger.warning("BIST ownership registry: %s has no name — skipped", entity_id)
        return None
    if category not in VALID_CATEGORIES:
        logger.warning(
            "BIST ownership registry: %s has unknown category %r — skipped", entity_id, category
        )
        return None

    sources = raw.get("sources")
    if not isinstance(sources, dict) or not sources:
        logger.warning("BIST ownership registry: %s declares no sources — skipped", entity_id)
        return None
    clean_sources: dict[str, dict[str, Any]] = {}
    for kind, keys in sources.items():
        if kind in VALID_SOURCES and isinstance(keys, dict):
            clean_sources[kind] = keys
        else:
            logger.warning(
                "BIST ownership registry: %s source %r is not usable — dropped", entity_id, kind
            )
    if not clean_sources:
        return None
    if "kap_fund" in clean_sources and not clean_sources["kap_fund"].get("code"):
        logger.warning("BIST ownership registry: %s kap_fund has no code — skipped", entity_id)
        return None

    aliases_raw = raw.get("aliases") or []
    aliases = tuple(a for a in aliases_raw if isinstance(a, str) and a.strip())
    if "shareholders" in clean_sources and not aliases:
        # An entity with no spelling to match on can never gain a position.
        logger.warning("BIST ownership registry: %s has no aliases — skipped", entity_id)
        return None

    order = raw.get("order")
    subtitle = raw.get("subtitle")
    note = raw.get("coverage_note")
    return EntityConfig(
        id=entity_id,
        name=name,
        category=category,
        subtitle=subtitle if isinstance(subtitle, str) and subtitle else None,
        order=order if isinstance(order, int) else 1_000,
        coverage_note=note if isinstance(note, str) and note else None,
        aliases=aliases,
        sources=clean_sources,
    )


def load_entities() -> list[EntityConfig]:
    """Every usable entity, in display order. Never raises; a bad file is an empty list."""
    payload = read_json_cache(ENTITIES_FILE)
    rows = payload.get("entities") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        logger.warning("BIST ownership registry missing or malformed at %s", ENTITIES_FILE)
        return []
    entities = [e for e in (_coerce_entity(r) for r in rows) if e is not None]
    seen: set[str] = set()
    unique: list[EntityConfig] = []
    for entity in entities:
        if entity.id in seen:
            logger.warning(
                "BIST ownership registry: duplicate id %s — later row dropped", entity.id
            )
            continue
        seen.add(entity.id)
        unique.append(entity)
    return sorted(unique, key=lambda e: (e.order, e.name))


class AliasIndex:
    """Holder name → entity id, built once per board read."""

    def __init__(self, entities: list[EntityConfig]) -> None:
        self._exact: dict[str, str] = {}
        for entity in entities:
            for alias in (entity.name, *entity.aliases):
                key = normalise_holder(alias)
                if not key:
                    continue
                if key in self._exact and self._exact[key] != entity.id:
                    # Two entities claiming one spelling is a registry bug, and
                    # the safe outcome is that neither gets the row.
                    logger.warning(
                        "BIST ownership registry: alias %r is claimed by both %s and %s",
                        alias,
                        self._exact[key],
                        entity.id,
                    )
                    self._exact[key] = ""
                    continue
                self._exact[key] = entity.id
        self._keys = sorted(self._exact, key=len)

    def match(self, holder_name: str) -> str | None:
        key = normalise_holder(holder_name)
        if not key:
            return None
        hit = self._exact.get(key)
        if hit:
            return hit
        if hit == "":
            return None
        if len(holder_name.strip()) < CLIP_LENGTH:
            return None
        # A clipped row: `Family Danışmanlık Gayrimenkul Ve Ticaret Anonim Ş`.
        # The alias is the full spelling; the row must be its prefix. Shortest
        # candidate first so a registry that lists both forms still resolves.
        candidates = [k for k in self._keys if k.startswith(key) and self._exact[k]]
        if len({self._exact[k] for k in candidates}) == 1:
            return self._exact[candidates[0]]
        return None
