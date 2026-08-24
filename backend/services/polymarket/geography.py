"""
Where a country sits on the map, and how to spot one in a market question.

Two tables, both boring on purpose.

`CENTROIDS` is the point a bubble is drawn at, computed once from the same
world outline the frontend renders (`public/world.geo.json`) so a bubble always
lands inside its own country's borders. Keyed by that file's own country names,
because a bubble placed by a name the map does not know is a bubble nobody sees.

Russia and Fiji are the two hand-set entries: both straddle the antimeridian, so
averaging their outlines puts Russia in Alaska and Fiji off West Africa. Their
published land centroids are used instead.

`ALIASES` is how a country is recognised in "Will Russia and Ukraine agree a
ceasefire?". Demonyms are included because market questions use them freely
("Iranian blockade", "German coalition"), and a handful of capitals are included
because a question naming a capital is a question about that country. This
matching is why the map layer built from it is labelled *derived* rather than
measured: the volume is a real measurement, the country attached to it is a rule
applied to a sentence.
"""

from __future__ import annotations

import re

CENTROIDS: dict[str, tuple[float, float]] = {
    "Afghanistan": (66.09, 33.86),
    "Albania": (20.03, 41.14),
    "Algeria": (2.6, 28.19),
    "Angola": (17.5, -12.29),
    "Antarctica": (31.22, -77.33),
    "Argentina": (-65.15, -35.22),
    "Armenia": (45.0, 40.22),
    "Australia": (134.38, -25.56),
    "Austria": (14.07, 47.61),
    "Azerbaijan": (47.68, 40.28),
    "Bahamas": (-77.92, 24.51),
    "Bangladesh": (90.27, 23.84),
    "Belarus": (27.98, 53.51),
    "Belgium": (4.58, 50.65),
    "Belize": (-88.7, 17.2),
    "Benin": (2.34, 9.65),
    "Bhutan": (90.47, 27.43),
    "Bolivia": (-64.64, -16.73),
    "Bosnia and Herz.": (17.82, 44.18),
    "Botswana": (23.77, -22.1),
    "Brazil": (-53.05, -10.81),
    "Brunei": (114.92, 4.69),
    "Bulgaria": (25.2, 42.75),
    "Burkina Faso": (-1.78, 12.31),
    "Burundi": (29.92, -3.38),
    "Cambodia": (104.87, 12.68),
    "Cameroon": (12.61, 5.66),
    "Canada": (-101.57, 57.75),
    "Central African Rep.": (20.38, 6.54),
    "Chad": (18.58, 15.33),
    "Chile": (-71.67, -37.35),
    "China": (103.86, 36.61),
    "Colombia": (-73.08, 3.93),
    "Congo": (15.13, -0.84),
    "Costa Rica": (-84.18, 9.97),
    "Croatia": (16.57, 45.02),
    "Cuba": (-78.96, 21.63),
    "Cyprus": (33.04, 34.91),
    "Czechia": (15.34, 49.78),
    "Côte d'Ivoire": (-5.61, 7.55),
    "Dem. Rep. Congo": (23.58, -2.85),
    "Denmark": (9.31, 56.22),
    "Djibouti": (42.5, 11.77),
    "Dominican Rep.": (-70.46, 18.88),
    "Ecuador": (-78.38, -1.45),
    "Egypt": (29.84, 26.51),
    "El Salvador": (-88.87, 13.72),
    "Eq. Guinea": (10.36, 1.65),
    "Eritrea": (38.67, 15.43),
    "Estonia": (25.83, 58.64),
    "Ethiopia": (39.55, 8.65),
    "Falkland Is.": (-59.42, -51.71),
    "Fiji": (178.0, -17.8),
    "Finland": (26.21, 64.5),
    "Fr. S. Antarctic Lands": (69.53, -49.31),
    "France": (2.34, 46.61),
    "Gabon": (11.69, -0.65),
    "Gambia": (-15.43, 13.48),
    "Georgia": (43.48, 42.16),
    "Germany": (10.29, 51.13),
    "Ghana": (-1.24, 7.93),
    "Greece": (22.56, 39.34),
    "Greenland": (-41.5, 74.77),
    "Guatemala": (-90.37, 15.7),
    "Guinea": (-11.06, 10.45),
    "Guinea-Bissau": (-15.11, 12.02),
    "Guyana": (-58.97, 4.79),
    "Haiti": (-72.66, 18.9),
    "Honduras": (-86.59, 14.82),
    "Hungary": (19.36, 47.2),
    "Iceland": (-18.76, 65.07),
    "India": (79.59, 22.93),
    "Indonesia": (114.02, -0.25),
    "Iran": (54.29, 32.52),
    "Iraq": (43.76, 33.04),
    "Ireland": (-8.01, 53.18),
    "Israel": (35.0, 31.49),
    "Italy": (12.22, 43.47),
    "Jamaica": (-77.33, 18.14),
    "Japan": (136.89, 36.02),
    "Jordan": (36.78, 31.25),
    "Kazakhstan": (67.28, 48.19),
    "Kenya": (37.79, 0.6),
    "Kosovo": (20.89, 42.58),
    "Kuwait": (47.6, 29.31),
    "Kyrgyzstan": (74.62, 41.51),
    "Laos": (103.75, 18.45),
    "Latvia": (24.84, 56.81),
    "Lebanon": (35.87, 33.91),
    "Lesotho": (28.17, -29.63),
    "Liberia": (-9.41, 6.43),
    "Libya": (17.97, 27.0),
    "Lithuania": (23.88, 55.28),
    "Luxembourg": (5.97, 49.76),
    "Macedonia": (21.7, 41.61),
    "Madagascar": (46.69, -19.36),
    "Malawi": (34.19, -13.17),
    "Malaysia": (114.67, 3.55),
    "Mali": (-3.54, 17.27),
    "Mauritania": (-10.33, 20.21),
    "Mexico": (-102.58, 23.93),
    "Moldova": (28.41, 47.2),
    "Mongolia": (102.95, 46.82),
    "Montenegro": (19.29, 42.79),
    "Morocco": (-8.42, 29.89),
    "Mozambique": (35.47, -17.23),
    "Myanmar": (96.51, 21.02),
    "N. Cyprus": (33.55, 35.27),
    "Namibia": (17.16, -22.1),
    "Nepal": (84.01, 28.24),
    "Netherlands": (5.51, 52.3),
    "New Caledonia": (165.53, -21.26),
    "New Zealand": (170.51, -43.99),
    "Nicaragua": (-85.02, 12.85),
    "Niger": (9.32, 17.35),
    "Nigeria": (8.0, 9.55),
    "North Korea": (127.16, 40.14),
    "Norway": (14.24, 64.54),
    "Oman": (56.1, 20.58),
    "Pakistan": (69.41, 29.97),
    "Palestine": (35.27, 31.94),
    "Panama": (-80.11, 8.53),
    "Papua New Guinea": (144.33, -6.65),
    "Paraguay": (-58.39, -23.25),
    "Peru": (-74.39, -9.19),
    "Philippines": (121.54, 15.75),
    "Poland": (19.31, 52.15),
    "Portugal": (-8.06, 39.63),
    "Puerto Rico": (-66.48, 18.24),
    "Qatar": (51.18, 25.32),
    "Romania": (24.94, 45.86),
    "Russia": (95.0, 62.0),
    "Rwanda": (29.92, -2.01),
    "S. Sudan": (30.2, 7.29),
    "Saudi Arabia": (44.52, 24.12),
    "Senegal": (-14.51, 14.36),
    "Serbia": (20.82, 44.23),
    "Sierra Leone": (-11.8, 8.53),
    "Slovakia": (19.51, 48.73),
    "Slovenia": (14.94, 46.13),
    "Solomon Is.": (159.11, -7.9),
    "Somalia": (45.72, 4.75),
    "Somaliland": (46.23, 9.76),
    "South Africa": (25.12, -28.96),
    "South Korea": (127.82, 36.43),
    "Spain": (-3.62, 40.35),
    "Sri Lanka": (80.67, 7.7),
    "Sudan": (29.86, 15.99),
    "Suriname": (-55.91, 4.12),
    "Sweden": (16.6, 62.81),
    "Switzerland": (8.12, 46.79),
    "Syria": (38.54, 35.01),
    "Taiwan": (120.98, 23.74),
    "Tajikistan": (71.03, 38.58),
    "Tanzania": (34.75, -6.26),
    "Thailand": (101.01, 15.02),
    "Timor-Leste": (125.97, -8.77),
    "Togo": (1.0, 8.44),
    "Trinidad and Tobago": (-61.33, 10.43),
    "Tunisia": (9.54, 34.17),
    "Turkey": (35.39, 38.99),
    "Turkmenistan": (59.27, 39.09),
    "Uganda": (32.36, 1.3),
    "Ukraine": (31.23, 49.15),
    "United Arab Emirates": (54.21, 23.87),
    "United Kingdom": (-2.66, 53.89),
    "United States of America": (-99.06, 39.5),
    "Uruguay": (-56.0, -32.78),
    "Uzbekistan": (63.2, 41.75),
    "Vanuatu": (166.91, -15.22),
    "Venezuela": (-66.17, 7.16),
    "Vietnam": (106.29, 16.65),
    "W. Sahara": (-12.14, 24.29),
    "Yemen": (47.53, 15.91),
    "Zambia": (27.73, -13.4),
    "Zimbabwe": (29.79, -18.91),
    "eSwatini": (31.39, -26.49),
}

#: Extra names for the countries that actually turn up in prediction markets.
#: The map's own country names are always matched too, so this table only has to
#: carry what a person would write instead of them.
ALIASES: dict[str, tuple[str, ...]] = {
    "United States of America": (
        "united states",
        "usa",
        "u.s.",
        "us",
        "america",
        "american",
        "washington",
    ),
    "United Kingdom": ("uk", "britain", "british", "england", "english", "london", "scotland"),
    "Russia": ("russian", "moscow", "kremlin"),
    "Ukraine": ("ukrainian", "kyiv", "kiev"),
    "China": ("chinese", "beijing", "prc"),
    "Taiwan": ("taiwanese", "taipei"),
    "Iran": ("iranian", "tehran"),
    "Israel": ("israeli", "jerusalem", "tel aviv"),
    "Germany": ("german", "berlin"),
    "France": ("french", "paris"),
    "Italy": ("italian", "rome"),
    "Spain": ("spanish", "madrid"),
    "Poland": ("polish", "warsaw"),
    "Turkey": ("turkish", "ankara", "istanbul", "türkiye"),
    "Japan": ("japanese", "tokyo"),
    "South Korea": ("korean", "seoul", "republic of korea"),
    "North Korea": ("pyongyang", "dprk"),
    "India": ("indian", "delhi", "new delhi"),
    "Pakistan": ("pakistani", "islamabad"),
    "Brazil": ("brazilian", "brasilia", "sao paulo"),
    "Argentina": ("argentine", "argentinian", "buenos aires"),
    "Mexico": ("mexican", "mexico city"),
    "Canada": ("canadian", "ottawa", "toronto"),
    "Venezuela": ("venezuelan", "caracas"),
    "Saudi Arabia": ("saudi", "riyadh"),
    "Syria": ("syrian", "damascus"),
    "Iraq": ("iraqi", "baghdad"),
    "Lebanon": ("lebanese", "beirut"),
    "Yemen": ("yemeni", "houthi", "houthis"),
    "Egypt": ("egyptian", "cairo"),
    "Ethiopia": ("ethiopian", "addis ababa"),
    "Nigeria": ("nigerian", "abuja", "lagos"),
    "South Africa": ("south african", "pretoria", "johannesburg"),
    "Australia": ("australian", "canberra", "sydney"),
    "Netherlands": ("dutch", "amsterdam", "the hague"),
    "Belgium": ("belgian", "brussels"),
    "Sweden": ("swedish", "stockholm"),
    "Norway": ("norwegian", "oslo"),
    "Finland": ("finnish", "helsinki"),
    "Denmark": ("danish", "copenhagen", "greenland"),
    "Switzerland": ("swiss", "bern", "zurich", "geneva"),
    "Austria": ("austrian", "vienna"),
    "Greece": ("greek", "athens"),
    "Portugal": ("portuguese", "lisbon"),
    "Ireland": ("irish", "dublin"),
    "Hungary": ("hungarian", "budapest"),
    "Romania": ("romanian", "bucharest"),
    "Czechia": ("czech", "prague", "czech republic"),
    "Belarus": ("belarusian", "minsk"),
    "Afghanistan": ("afghan", "kabul", "taliban"),
    "Indonesia": ("indonesian", "jakarta"),
    "Thailand": ("thai", "bangkok"),
    "Vietnam": ("vietnamese", "hanoi"),
    "Philippines": ("filipino", "manila"),
    "Singapore": ("singaporean",),
    "New Zealand": ("kiwi", "wellington"),
    "Colombia": ("colombian", "bogota"),
    "Chile": ("chilean", "santiago"),
    "Peru": ("peruvian", "lima"),
    "Cuba": ("cuban", "havana"),
    "Libya": ("libyan", "tripoli"),
    "Sudan": ("sudanese", "khartoum"),
    "Somalia": ("somali", "mogadishu"),
    "Myanmar": ("burmese", "burma", "yangon"),
    "Kazakhstan": ("kazakh", "astana"),
    "Qatar": ("qatari", "doha"),
    "United Arab Emirates": ("uae", "emirati", "dubai", "abu dhabi"),
}

#: Words that name a country but almost never mean it in a market question.
#: "Georgia" is a US state far more often than it is the country, and "Jordan"
#: is a basketball player. Both are matched only via their unambiguous aliases.
AMBIGUOUS = frozenset({"Georgia", "Jordan", "Chad", "Turkey"})

_PATTERNS: dict[str, re.Pattern[str]] = {}


def _patterns() -> dict[str, re.Pattern[str]]:
    """Compiled matchers, built once."""
    if _PATTERNS:
        return _PATTERNS
    for country in CENTROIDS:
        terms = list(ALIASES.get(country, ()))
        # The map's own name matches too, unless it is a word that usually means
        # something else — "Turkey" reaches the map through "turkish"/"ankara".
        if country not in AMBIGUOUS:
            terms.append(country.lower())
        if not terms:
            continue
        joined = "|".join(re.escape(t) for t in sorted(set(terms), key=len, reverse=True))
        _PATTERNS[country] = re.compile(rf"\b({joined})\b", re.IGNORECASE)
    return _PATTERNS


def countries_in(*texts: str) -> list[str]:
    """
    Every country named in the given text, by the map's own country names.

    Deliberately generous with aliases and strict with word boundaries: a market
    asking about "the Iranian blockade" is about Iran, while one about "Warner
    Bros" is not about war.
    """
    haystack = " ".join(t for t in texts if t)
    if not haystack.strip():
        return []
    return [country for country, pattern in _patterns().items() if pattern.search(haystack)]
