"""
Macro Router
Serves the macro board: commodity futures, benchmark equity indices, the dollar
index and the ratios derived from them.

`UpstreamUnavailable` surfaces as a 503 rather than an empty board, for the same
reason the home router does it: a page handed `[]` renders the outage as the
claim that gold, oil and the S&P 500 all have nothing to report.

The regime endpoint below is the one exception, and for the same reason rather
than in spite of it. An empty board would misrepresent the outage; an explicit
"Unavailable" label states it. And the board endpoint is already 503-ing beside
it, so a second failure here would only make the page report one outage twice.
"""

from fastapi import APIRouter, HTTPException

from services.home_service import UpstreamUnavailable
from services.macro_board_service import fetch_macro_board
from services.macro_regime import build_regime, regime_note
from services.neh_index_service import fetch_neh_index
from services.pentagon_pizza_service import fetch_pizza_index

router = APIRouter()


def _unavailable(error: UpstreamUnavailable) -> HTTPException:
    return HTTPException(status_code=503, detail=str(error))


@router.get("/api/macro/board")
async def get_macro_board():
    """Commodities, global indices and macro ratios in one cached payload."""
    try:
        return await fetch_macro_board()
    except UpstreamUnavailable as error:
        raise _unavailable(error) from error


@router.get("/api/macro/regime")
async def get_macro_regime():
    """
    The cross-asset regime read, plus the note explaining it.

    The label and the score are computed in Python and are always present; the
    note is decoration and may be absent, still being written, or unavailable
    because the model layer is off. The page renders in every one of those cases.

    Notes are written on the server's own provider chain rather than a signed-in
    user's, because one note is generated per board state and served to everyone
    who loads the page. Routing it through a user's own key would bill one reader
    for every other reader's copy.
    """
    try:
        board = await fetch_macro_board()
    except UpstreamUnavailable:
        # An empty board scores nothing, so this lands on the "Unavailable" label
        # with every component named as missing — which is precisely the truth.
        board = {}

    regime = build_regime(board)
    return {**regime, "note": await regime_note(regime)}


@router.get("/api/macro/pizza-index")
async def get_pizza_index():
    """
    The Pentagon Pizza Index.

    Deliberately the one endpoint on this router that cannot fail. The two above
    answer 503 because an empty macro board would misstate an outage as a market
    with nothing to report; this one carries an OSINT novelty, and the same logic
    runs the other way — a scrape that broke must not be able to take the page
    its panel sits on down with it. The service answers `status: "unavailable"`
    instead, which the panel renders as its own state.
    """
    return await fetch_pizza_index()


@router.get("/api/macro/neh-index")
async def get_neh_index():
    """
    The Nothing Ever Happens Index.

    Cannot fail, for the reason the pizza endpoint cannot: the two share one
    panel, and a failure of either has to arrive as a reading that says so
    rather than as an error the panel has no shape for.
    """
    return await fetch_neh_index()
