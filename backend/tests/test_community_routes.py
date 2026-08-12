"""
Tests for the community router's auth boundaries and error mapping.

The service layer is stubbed out: what is being checked here is who may call
what, and that a service error becomes the right status code. The backend runs
with the service-role key and bypasses row-level security, so the 403 on
someone else's post is the only thing enforcing ownership — it is worth a test.
"""

from datetime import datetime, UTC

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from models.community import Post, PostAuthor, VoteResult
from routers import community as community_router
from services.community import comments as comment_service
from services.community import media as media_service
from services.community import posts as post_service
from services.community import votes as vote_service
from services.community.errors import InvalidRequest, NotFound, NotOwner, UpstreamFailure

GOOD = {"Authorization": "Bearer good-token"}
NOW = datetime(2026, 8, 6, 12, 0, tzinfo=UTC)


def _post(post_id="post-1", author_id="user-abc"):
    return Post(
        id=post_id,
        type="thought",
        post_kind="text",
        title="A title",
        content="A body",
        score=3,
        comments_count=0,
        is_edited=False,
        created_at=NOW,
        author=PostAuthor(id=author_id, full_name="Mira"),
        my_vote=0,
    )


@pytest.fixture
def client(patch_supabase):
    app = FastAPI()
    app.include_router(community_router.router)
    return TestClient(app)


# ── reads are public ─────────────────────────────────────────────────────────


def test_feed_is_readable_signed_out(client, monkeypatch):
    seen = {}

    async def _list_posts(**kwargs):
        seen.update(kwargs)
        return [_post()]

    monkeypatch.setattr(post_service, "list_posts", _list_posts)

    response = client.get("/api/community/posts")

    assert response.status_code == 200
    assert len(response.json()["posts"]) == 1
    # Signed out, so there is no viewer whose vote could be reported.
    assert seen["viewer_id"] is None


def test_feed_passes_the_signed_in_viewer_through(client, monkeypatch):
    seen = {}

    async def _list_posts(**kwargs):
        seen.update(kwargs)
        return []

    monkeypatch.setattr(post_service, "list_posts", _list_posts)

    client.get("/api/community/posts?sort=top", headers=GOOD)

    assert seen["viewer_id"] == "user-abc"
    assert seen["sort"] == "top"


def test_has_more_is_true_only_when_the_page_came_back_full(client, monkeypatch):
    async def _list_posts(**kwargs):
        return [_post(f"p{i}") for i in range(kwargs["limit"])]

    monkeypatch.setattr(post_service, "list_posts", _list_posts)

    assert client.get("/api/community/posts?limit=2").json()["has_more"] is True

    async def _short_page(**_kwargs):
        return [_post()]

    monkeypatch.setattr(post_service, "list_posts", _short_page)

    assert client.get("/api/community/posts?limit=2").json()["has_more"] is False


def test_an_unknown_sort_is_rejected_before_reaching_the_service(client):
    assert client.get("/api/community/posts?sort=controversial").status_code == 422


def test_comments_are_readable_signed_out(client, monkeypatch):
    async def _list_comments(_post_id, viewer_id=None):
        return [], 0

    monkeypatch.setattr(comment_service, "list_comments", _list_comments)

    response = client.get("/api/community/posts/post-1/comments")

    assert response.status_code == 200
    assert response.json() == {"comments": [], "total": 0}


# ── writes require a session ─────────────────────────────────────────────────


@pytest.mark.parametrize(
    "method,path,body",
    [
        ("post", "/api/community/posts", {"type": "thought", "content": "hi"}),
        ("patch", "/api/community/posts/post-1", {"content": "edited"}),
        ("delete", "/api/community/posts/post-1", None),
        ("post", "/api/community/posts/post-1/comments", {"content": "hi"}),
        ("patch", "/api/community/comments/c-1", {"content": "edited"}),
        ("delete", "/api/community/comments/c-1", None),
        ("post", "/api/community/posts/post-1/vote", {"value": 1}),
        ("post", "/api/community/comments/c-1/vote", {"value": 1}),
        ("post", "/api/community/link-preview", {"url": "https://example.com"}),
    ],
)
def test_writes_are_401_without_a_token(client, method, path, body):
    response = getattr(client, method)(path, json=body) if body else getattr(client, method)(path)

    assert response.status_code == 401


def test_voting_signed_in_returns_the_authoritative_score(client, monkeypatch):
    async def _set_post_vote(*, user_id, post_id, value):
        assert user_id == "user-abc"
        return VoteResult(score=7, my_vote=value)

    monkeypatch.setattr(vote_service, "set_post_vote", _set_post_vote)

    response = client.post("/api/community/posts/post-1/vote", json={"value": -1}, headers=GOOD)

    assert response.status_code == 200
    assert response.json() == {"score": 7, "my_vote": -1}


def test_a_vote_value_outside_the_three_allowed_is_rejected(client):
    response = client.post("/api/community/posts/post-1/vote", json={"value": 5}, headers=GOOD)

    assert response.status_code == 422


def test_the_author_comes_from_the_token_not_the_body(client, monkeypatch):
    """`user_id` in the body must not be able to forge authorship."""
    captured = {}

    async def _create_post(**kwargs):
        captured.update(kwargs)
        return _post()

    monkeypatch.setattr(post_service, "create_post", _create_post)

    client.post(
        "/api/community/posts",
        json={"type": "thought", "content": "hi", "user_id": "somebody-else"},
        headers=GOOD,
    )

    assert captured["user_id"] == "user-abc"


# ── error mapping ────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "error,expected",
    [
        (NotFound("gone"), 404),
        (NotOwner("not yours"), 403),
        (InvalidRequest("bad"), 400),
        (UpstreamFailure("postgres said no"), 502),
    ],
)
def test_service_errors_map_onto_status_codes(client, monkeypatch, error, expected):
    async def _update_post(**_kwargs):
        raise error

    monkeypatch.setattr(post_service, "update_post", _update_post)

    response = client.patch("/api/community/posts/post-1", json={"content": "edited"}, headers=GOOD)

    assert response.status_code == expected


def test_editing_someone_elses_post_is_403(client, monkeypatch):
    async def _update_post(**_kwargs):
        raise NotOwner("post belongs to another user")

    monkeypatch.setattr(post_service, "update_post", _update_post)

    response = client.patch("/api/community/posts/post-1", json={"content": "edited"}, headers=GOOD)

    assert response.status_code == 403
    # The message stays generic: whose post it is, is not the caller's business.
    assert "another user" not in response.json()["detail"]


def test_deleting_your_own_post_is_204(client, monkeypatch):
    async def _delete_post(*, post_id, user_id):
        assert (post_id, user_id) == ("post-1", "user-abc")

    monkeypatch.setattr(post_service, "delete_post", _delete_post)

    assert client.delete("/api/community/posts/post-1", headers=GOOD).status_code == 204


# ── upload ───────────────────────────────────────────────────────────────────


def test_an_oversized_upload_is_413_before_the_bucket_is_touched(client, monkeypatch):
    async def _never(**_kwargs):
        raise AssertionError("the service should not have been reached")

    monkeypatch.setattr(media_service, "upload_image", _never)
    oversized = b"\x89PNG\r\n\x1a\n" + b"0" * (media_service.MAX_BYTES + 16)

    response = client.post(
        "/api/community/media",
        files={"file": ("huge.png", oversized, "image/png")},
        headers=GOOD,
    )

    assert response.status_code == 413
