"""
Tests for a reader-supplied LLM endpoint.

Two things are being defended. The first is the feature: Ollama runs on the
reader's machine, so "keep using my own free local model" only works if they can
name an endpoint the server can reach. The second is the hole that opens if the
first is done carelessly — a signed-in reader making the server fetch an address
of their choosing.
"""

import pytest

from services.llm import base_url as rules
from services.llm.base_url import InvalidBaseURL
from services.llm.client import build_provider
from services.llm.presets import accepts_base_url, self_hosted_provider_names


class TestValidation:
    def test_blank_means_use_the_server_setting(self):
        assert rules.validate("") == ""
        assert rules.validate(None) == ""
        assert rules.validate("   ") == ""

    def test_accepts_a_public_endpoint(self):
        assert rules.validate("https://example.com/v1") == "https://example.com/v1"

    def test_strips_whitespace_and_a_trailing_slash(self):
        """So the same endpoint typed two ways is one stored value."""
        assert rules.validate("  https://example.com/v1/  ") == "https://example.com/v1"

    @pytest.mark.parametrize(
        "url",
        [
            "http://localhost:11434",
            "http://127.0.0.1:11434",
            "http://[::1]:11434",
            "http://10.0.0.5:11434",
            "http://192.168.1.10:11434",
            "http://172.16.0.4:11434",
            # The one that matters most: cloud instance credentials.
            "http://169.254.169.254/latest/meta-data/",
            "http://0.0.0.0:11434",
        ],
    )
    def test_refuses_addresses_the_public_internet_cannot_reach(self, url):
        """
        The SSRF guard.

        A reader's endpoint is only useful when it names a machine the server is
        not already next to, so nothing legitimate is lost — and an operator who
        wants localhost sets OLLAMA_BASE_URL, which never comes through here.
        """
        with pytest.raises(InvalidBaseURL):
            rules.validate(url)

    def test_a_hostname_resolving_to_a_private_address_is_refused(self, monkeypatch):
        """Checking the text alone would let `ollama.internal` through."""
        monkeypatch.setattr(
            rules, "_resolved_addresses", lambda host: [rules.ipaddress.ip_address("10.1.2.3")]
        )
        with pytest.raises(InvalidBaseURL):
            rules.validate("https://ollama.internal")

    def test_every_resolved_address_is_checked(self, monkeypatch):
        """A name answering with one public and one private address is refused."""
        monkeypatch.setattr(
            rules,
            "_resolved_addresses",
            lambda host: [
                rules.ipaddress.ip_address("93.184.216.34"),
                rules.ipaddress.ip_address("127.0.0.1"),
            ],
        )
        with pytest.raises(InvalidBaseURL):
            rules.validate("https://split-horizon.example.com")

    @pytest.mark.parametrize("url", ["ftp://example.com", "file:///etc/passwd", "example.com"])
    def test_refuses_a_scheme_that_is_not_http(self, url):
        with pytest.raises(InvalidBaseURL):
            rules.validate(url)

    def test_refuses_credentials_in_the_url(self):
        """They would be logged by anything that prints the endpoint."""
        with pytest.raises(InvalidBaseURL):
            rules.validate("https://user:secret@example.com")

    def test_refuses_an_unreasonably_long_value(self):
        with pytest.raises(InvalidBaseURL):
            rules.validate("https://example.com/" + "a" * rules.MAX_LENGTH)

    def test_refuses_a_name_that_does_not_resolve(self):
        with pytest.raises(InvalidBaseURL):
            rules.validate("https://nonesuch.invalid")


class TestWhichProvidersAcceptOne:
    def test_the_self_hosted_presets_do(self):
        assert self_hosted_provider_names() == ["ollama", "custom"]
        assert accepts_base_url("ollama")
        assert accepts_base_url("CUSTOM")

    @pytest.mark.parametrize("name", ["openai", "anthropic", "mistral", "groq", "gemini"])
    def test_the_cloud_presets_do_not(self, name):
        """
        Redirecting one would mean the server posting a reader's own API key to
        a host named in a request. Nothing needs OpenAI to live elsewhere.
        """
        assert not accepts_base_url(name)


class TestBuildProvider:
    def test_a_readers_endpoint_is_used_for_ollama(self):
        provider = build_provider("ollama", "qwen3.6:35b-a3b", "", "https://tunnel.example.com")
        assert provider is not None
        assert provider.base_url == "https://tunnel.example.com"

    def test_ollama_falls_back_to_the_server_setting(self, monkeypatch):
        from config import settings

        monkeypatch.setattr(settings, "OLLAMA_BASE_URL", "http://localhost:11434")
        provider = build_provider("ollama", "qwen3.6:35b-a3b", "", "")
        assert provider is not None
        assert provider.base_url == "http://localhost:11434"

    def test_a_cloud_preset_ignores_a_supplied_endpoint(self):
        """Defence in depth: the storage layer refuses it, and so does this."""
        provider = build_provider("openai", "gpt-4.1-mini", "k", "https://elsewhere.example.com")
        assert provider is not None
        assert provider.base_url == "https://api.openai.com/v1"

    def test_custom_uses_a_readers_endpoint(self):
        provider = build_provider("custom", "my-model", "k", "https://vllm.example.com/v1")
        assert provider is not None
        assert provider.base_url == "https://vllm.example.com/v1"

    def test_custom_without_any_endpoint_is_unbuildable(self, monkeypatch):
        """Rather than dialling something arbitrary."""
        from config import settings

        monkeypatch.setattr(settings, "LLM_BASE_URL", "")
        assert build_provider("custom", "my-model", "k", "") is None

    def test_the_endpoint_never_appears_in_the_repr(self):
        """The key must not leak through it either; both live on the same object."""
        provider = build_provider("custom", "m", "sk-secret", "https://vllm.example.com/v1")
        assert "sk-secret" not in repr(provider)
