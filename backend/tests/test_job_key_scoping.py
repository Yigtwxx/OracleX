"""
Whose key pays for a single-flighted job.

Dedup on the artifact alone was fine until bring-your-own-key existed. After it,
whoever clicked first decided whose credential was billed: a reader with a
configured key could re-attach to a run already going on the server's provider
and never learn their key was unused, or have their key spent on somebody
else's report.
"""

import pytest

from services import analysis_jobs
from services.llm.base import LLMProvider


class StubProvider(LLMProvider):
    def __init__(self, name: str, api_key: str):
        super().__init__(name=name, base_url="https://example.com", model="m", api_key=api_key)

    async def generate(self, req):  # noqa: ANN001
        return ""

    async def health(self) -> bool:
        return True

    async def list_models(self) -> list[str]:
        return ["m"]


@pytest.fixture
def no_personal_keys(monkeypatch):
    from services import llm

    async def none(_user_id, _feature):
        return None

    monkeypatch.setattr(llm, "provider_for", none)


@pytest.fixture
def personal_keys(monkeypatch):
    """Two readers with their own keys, and a third sharing one of them."""
    from services import llm

    keys = {"ada": "sk-ada", "bob": "sk-bob", "cal": "sk-ada"}

    async def resolve(user_id, _feature):
        secret = keys.get(user_id)
        return StubProvider("mistral", secret) if secret else None

    monkeypatch.setattr(llm, "provider_for", resolve)


class TestScopedKey:
    @pytest.mark.asyncio
    async def test_anonymous_callers_share_one_run(self, no_personal_keys):
        assert await analysis_jobs.scoped_key("daily", None, "reports") == "daily"

    @pytest.mark.asyncio
    async def test_readers_on_the_server_chain_share_one_run(self, no_personal_keys):
        """
        The common case, and the thing single-flight is for. Splitting on
        user_id unconditionally would have thrown it away.
        """
        ada = await analysis_jobs.scoped_key("daily", "ada", "reports")
        bob = await analysis_jobs.scoped_key("daily", "bob", "reports")
        assert ada == bob == "daily"

    @pytest.mark.asyncio
    async def test_a_reader_with_their_own_key_gets_their_own_run(self, personal_keys):
        shared = await analysis_jobs.scoped_key("daily", None, "reports")
        ada = await analysis_jobs.scoped_key("daily", "ada", "reports")

        assert ada != shared
        assert ada.startswith("daily:")

    @pytest.mark.asyncio
    async def test_two_readers_with_different_keys_do_not_share(self, personal_keys):
        ada = await analysis_jobs.scoped_key("daily", "ada", "reports")
        bob = await analysis_jobs.scoped_key("daily", "bob", "reports")
        assert ada != bob

    @pytest.mark.asyncio
    async def test_two_readers_with_the_same_credential_do_share(self, personal_keys):
        """
        Keyed on the quota bucket, not the user: the same credential draws on
        one quota, so sharing is both cheaper and what either would have got.
        """
        ada = await analysis_jobs.scoped_key("daily", "ada", "reports")
        cal = await analysis_jobs.scoped_key("daily", "cal", "reports")
        assert ada == cal

    @pytest.mark.asyncio
    async def test_the_key_never_contains_the_credential(self, personal_keys):
        """It is logged on every reuse."""
        key = await analysis_jobs.scoped_key("daily", "ada", "reports")
        assert "sk-ada" not in key

    @pytest.mark.asyncio
    async def test_different_artifacts_stay_different(self, personal_keys):
        daily = await analysis_jobs.scoped_key("daily", "ada", "reports")
        weekly = await analysis_jobs.scoped_key("weekly", "ada", "reports")
        assert daily != weekly

    @pytest.mark.asyncio
    async def test_a_feature_the_reader_did_not_enable_shares(self, personal_keys, monkeypatch):
        """
        `provider_for` returns None for a feature whose toggle is off, so that
        run goes on the server chain and may be shared like anyone else's.
        """
        from services import llm

        async def only_chat(user_id, feature):
            if feature != "chat":
                return None
            return StubProvider("mistral", "sk-ada")

        monkeypatch.setattr(llm, "provider_for", only_chat)

        assert await analysis_jobs.scoped_key("daily", "ada", "reports") == "daily"
        assert await analysis_jobs.scoped_key("daily", "ada", "chat") != "daily"
