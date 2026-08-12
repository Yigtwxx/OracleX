"""
Macro Router
Serves the macro board: commodity futures, benchmark equity indices, the dollar
index and the ratios derived from them.

`UpstreamUnavailable` surfaces as a 503 rather than an empty board, for the same
reason the home router does it: a page handed `[]` renders the outage as the
claim that gold, oil and the S&P 500 all have nothing to report.
"""

from fastapi import APIRouter, HTTPException

from services.home_service import UpstreamUnavailable
from services.macro_board_service import fetch_macro_board

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
