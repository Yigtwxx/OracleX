"""
Tests for the community comment tree.

`build_tree` and `to_comment` are the two pieces of comment handling that hold
real logic and touch no database, which makes them the two worth pinning down.
"""

from datetime import datetime, UTC

from services.community.comments import build_tree, to_comment

NOW = datetime(2026, 8, 6, 12, 0, tzinfo=UTC)


def _row(comment_id, *, parent=None, depth=0, deleted=False, author="Mira", score=0):
    return {
        "id": comment_id,
        "post_id": "post-1",
        "parent_id": parent,
        "user_id": f"user-{author}",
        "content": None if deleted else f"body of {comment_id}",
        "score": score,
        "depth": depth,
        "is_edited": False,
        "deleted_at": NOW.isoformat() if deleted else None,
        "created_at": NOW,
        "updated_at": NOW,
        "author_name": None if deleted else author,
        "author_avatar_url": None,
        "author_plan": None,
        "my_vote": 0,
    }


# ── to_comment ───────────────────────────────────────────────────────────────


def test_live_comment_keeps_its_author_and_body():
    comment = to_comment(_row("c1"))

    assert comment.is_deleted is False
    assert comment.content == "body of c1"
    assert comment.author.full_name == "Mira"
    assert comment.author.id == "user-Mira"


def test_tombstoned_comment_discloses_neither_body_nor_author():
    comment = to_comment(_row("c1", deleted=True))

    assert comment.is_deleted is True
    assert comment.content is None
    assert comment.author.full_name is None
    # The user id is withheld too — otherwise "who deleted this" is a lookup away.
    assert comment.author.id is None


# ── build_tree ───────────────────────────────────────────────────────────────


def test_flat_comments_become_roots():
    tree = build_tree([to_comment(_row("a")), to_comment(_row("b"))])

    assert [c.id for c in tree] == ["a", "b"]
    assert all(c.replies == [] for c in tree)


def test_replies_nest_under_their_parent():
    rows = [
        _row("root"),
        _row("child", parent="root", depth=1),
        _row("grandchild", parent="child", depth=2),
    ]
    tree = build_tree([to_comment(r) for r in rows])

    assert len(tree) == 1
    root = tree[0]
    assert [c.id for c in root.replies] == ["child"]
    assert [c.id for c in root.replies[0].replies] == ["grandchild"]


def test_siblings_keep_their_input_order():
    rows = [
        _row("root"),
        _row("first", parent="root", depth=1),
        _row("second", parent="root", depth=1),
    ]
    tree = build_tree([to_comment(r) for r in rows])

    assert [c.id for c in tree[0].replies] == ["first", "second"]


def test_a_tombstoned_parent_still_carries_its_replies():
    """The whole reason deletion is a tombstone rather than a DELETE."""
    rows = [
        _row("root", deleted=True),
        _row("child", parent="root", depth=1),
    ]
    tree = build_tree([to_comment(r) for r in rows])

    assert tree[0].is_deleted is True
    assert [c.id for c in tree[0].replies] == ["child"]
    assert tree[0].replies[0].content == "body of child"


def test_a_reply_whose_parent_is_absent_is_promoted_not_dropped():
    """Losing a comment silently is worse than showing it at the wrong depth."""
    tree = build_tree([to_comment(_row("orphan", parent="missing", depth=1))])

    assert [c.id for c in tree] == ["orphan"]


def test_build_tree_is_idempotent():
    """Called twice on the same objects, replies must not double up."""
    comments = [to_comment(_row("root")), to_comment(_row("child", parent="root", depth=1))]

    build_tree(comments)
    tree = build_tree(comments)

    assert len(tree[0].replies) == 1
