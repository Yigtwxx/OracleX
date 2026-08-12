"""
Up/down voting on posts and comments.

The `score` column is maintained by database triggers
(`trg_community_post_score`, `trg_community_comment_score`), so nothing here
writes it. That is the point of the trigger: the previous implementation read
the count, added one in Python and wrote it back, which loses a vote whenever
two land at the same time.
"""

import logging
from typing import Optional

from models.community import VoteResult

from . import _db
from .errors import NotFound

logger = logging.getLogger(__name__)

POST_VOTES = "community_post_votes"
COMMENT_VOTES = "community_comment_votes"


async def set_post_vote(*, user_id: str, post_id: str, value: int) -> VoteResult:
    """Cast, flip, or clear (`value=0`) the caller's vote on a post."""
    await _write_vote(
        table=POST_VOTES,
        key_column="post_id",
        key_value=post_id,
        user_id=user_id,
        value=value,
    )
    score = await _read_score("community_posts", post_id)
    return VoteResult(score=score, my_vote=value)


async def set_comment_vote(*, user_id: str, comment_id: str, value: int) -> VoteResult:
    await _write_vote(
        table=COMMENT_VOTES,
        key_column="comment_id",
        key_value=comment_id,
        user_id=user_id,
        value=value,
    )
    score = await _read_score("community_comments", comment_id)
    return VoteResult(score=score, my_vote=value)


async def _write_vote(
    *, table: str, key_column: str, key_value: str, user_id: str, value: int
) -> None:
    if value == 0:
        await _db.table_op(
            lambda client: (
                client.table(table)
                .delete()
                .eq(key_column, key_value)
                .eq("user_id", user_id)
                .execute()
            ),
            what=f"clear vote on {key_column}",
        )
        return

    # The composite primary key (target, user) makes this an idempotent upsert:
    # voting the same way twice is a no-op, flipping updates in place.
    await _db.table_op(
        lambda client: (
            client.table(table)
            .upsert(
                {key_column: key_value, "user_id": user_id, "value": value},
                on_conflict=f"{key_column},user_id",
            )
            .execute()
        ),
        what=f"cast vote on {key_column}",
    )


async def _read_score(table: str, row_id: str) -> int:
    """
    Read back the score the trigger just wrote.

    A second round-trip rather than trusting a locally computed number: the
    authoritative value is whatever the trigger recomputed from the vote table,
    including any votes that landed concurrently with this one.
    """
    data = await _db.table_op(
        lambda client: client.table(table).select("score").eq("id", row_id).execute(),
        what=f"read {table} score",
    )
    if not data:
        raise NotFound(f"{table} row {row_id} does not exist")
    score: Optional[int] = data[0].get("score")
    return score or 0
