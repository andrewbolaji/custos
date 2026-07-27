"""Tests for CUSTOS_LLM_PROVIDER factory selection.

Mirrors the coverage pattern used for CUSTOS_VECTOR_BACKEND / CUSTOS_AGENT_RUNTIME:
every valid provider value, plus the error case for an unknown one. Bedrock
construction is mocked; no live Bedrock or Anthropic call is made.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from custos.llm import BedrockLLM, ClaudeLLM
from custos.llm_config import get_llm, get_provider


class TestGetProvider:
    def test_defaults_to_anthropic(self, monkeypatch) -> None:
        monkeypatch.delenv("CUSTOS_LLM_PROVIDER", raising=False)
        assert get_provider() == "anthropic"

    def test_reads_env_var_case_insensitively(self, monkeypatch) -> None:
        monkeypatch.setenv("CUSTOS_LLM_PROVIDER", "BEDROCK")
        assert get_provider() == "bedrock"


class TestGetLLMFactory:
    def test_unset_returns_claude_llm(self, monkeypatch) -> None:
        monkeypatch.delenv("CUSTOS_LLM_PROVIDER", raising=False)
        llm = get_llm(api_key="sk-test")
        assert isinstance(llm, ClaudeLLM)

    def test_explicit_anthropic_returns_claude_llm(self, monkeypatch) -> None:
        monkeypatch.setenv("CUSTOS_LLM_PROVIDER", "anthropic")
        llm = get_llm(api_key="sk-test")
        assert isinstance(llm, ClaudeLLM)

    def test_bedrock_returns_bedrock_llm(self, monkeypatch) -> None:
        monkeypatch.setenv("CUSTOS_LLM_PROVIDER", "bedrock")
        with patch("custos.llm.anthropic.AnthropicBedrock") as mock_bedrock:
            mock_bedrock.return_value = MagicMock()
            llm = get_llm(api_key=None)
        assert isinstance(llm, BedrockLLM)

    def test_unknown_provider_raises_naming_both_valid_values(self, monkeypatch) -> None:
        monkeypatch.setenv("CUSTOS_LLM_PROVIDER", "openai")
        with pytest.raises(ValueError) as exc_info:
            get_llm()
        message = str(exc_info.value)
        assert "openai" in message
        assert "anthropic" in message
        assert "bedrock" in message

    def test_on_api_call_forwarded_to_claude_llm(self, monkeypatch) -> None:
        monkeypatch.delenv("CUSTOS_LLM_PROVIDER", raising=False)
        callback = MagicMock()
        llm = get_llm(api_key="sk-test", on_api_call=callback)
        llm.notify_api_call()
        callback.assert_called_once()

    def test_on_api_call_forwarded_to_bedrock_llm(self, monkeypatch) -> None:
        monkeypatch.setenv("CUSTOS_LLM_PROVIDER", "bedrock")
        callback = MagicMock()
        with patch("custos.llm.anthropic.AnthropicBedrock") as mock_bedrock:
            mock_bedrock.return_value = MagicMock()
            llm = get_llm(on_api_call=callback)
        llm.notify_api_call()
        callback.assert_called_once()
