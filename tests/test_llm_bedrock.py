"""Tests for BedrockLLM: model default, region precedence, and credentials.

These tests do NOT make live Bedrock calls. anthropic.AnthropicBedrock is
mocked at construction so no boto3 credential resolution or network call
happens. The account these were developed against has a token-per-day quota
of zero pending an AWS support case, so a live call would return
ThrottlingException regardless; that is expected and out of scope here.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from custos.interfaces import Chunk
from custos.llm import DEFAULT_BEDROCK_MODEL, BedrockLLM


def _make_chunk(chunk_id: str, doc_id: str, text: str) -> Chunk:
    return Chunk(
        chunk_id=chunk_id,
        doc_id=doc_id,
        text=text,
        section_path=["Section"],
        char_start=0,
        char_end=len(text),
        permissions=["general"],
    )


class TestBedrockLLMModelDefault:
    """The Bedrock model ID defaults to the verified us.-prefixed inference profile."""

    def test_default_model_is_us_prefixed_constant(self, monkeypatch) -> None:
        monkeypatch.delenv("CUSTOS_BEDROCK_MODEL", raising=False)
        assert DEFAULT_BEDROCK_MODEL == "us.anthropic.claude-sonnet-4-6"

        with patch("custos.llm.anthropic.AnthropicBedrock") as mock_bedrock:
            mock_bedrock.return_value = MagicMock()
            llm = BedrockLLM()

        assert llm.model == DEFAULT_BEDROCK_MODEL

    def test_env_var_overrides_model(self, monkeypatch) -> None:
        monkeypatch.setenv("CUSTOS_BEDROCK_MODEL", "us.anthropic.claude-haiku-4-5")

        with patch("custos.llm.anthropic.AnthropicBedrock") as mock_bedrock:
            mock_bedrock.return_value = MagicMock()
            llm = BedrockLLM()

        assert llm.model == "us.anthropic.claude-haiku-4-5"

    def test_explicit_model_param_wins_over_env(self, monkeypatch) -> None:
        monkeypatch.setenv("CUSTOS_BEDROCK_MODEL", "us.anthropic.claude-haiku-4-5")

        with patch("custos.llm.anthropic.AnthropicBedrock") as mock_bedrock:
            mock_bedrock.return_value = MagicMock()
            llm = BedrockLLM(model="us.anthropic.claude-opus-4-5")

        assert llm.model == "us.anthropic.claude-opus-4-5"


class TestBedrockLLMRegionPrecedence:
    """Region resolves CUSTOS_BEDROCK_REGION > AWS_REGION > us-east-1."""

    def test_custos_bedrock_region_takes_precedence(self, monkeypatch) -> None:
        monkeypatch.setenv("CUSTOS_BEDROCK_REGION", "eu-west-1")
        monkeypatch.setenv("AWS_REGION", "ap-southeast-2")

        with patch("custos.llm.anthropic.AnthropicBedrock") as mock_bedrock:
            mock_bedrock.return_value = MagicMock()
            BedrockLLM()

        _, kwargs = mock_bedrock.call_args
        assert kwargs["aws_region"] == "eu-west-1"

    def test_falls_back_to_aws_region(self, monkeypatch) -> None:
        monkeypatch.delenv("CUSTOS_BEDROCK_REGION", raising=False)
        monkeypatch.setenv("AWS_REGION", "ap-southeast-2")

        with patch("custos.llm.anthropic.AnthropicBedrock") as mock_bedrock:
            mock_bedrock.return_value = MagicMock()
            BedrockLLM()

        _, kwargs = mock_bedrock.call_args
        assert kwargs["aws_region"] == "ap-southeast-2"

    def test_falls_back_to_us_east_1(self, monkeypatch) -> None:
        monkeypatch.delenv("CUSTOS_BEDROCK_REGION", raising=False)
        monkeypatch.delenv("AWS_REGION", raising=False)

        with patch("custos.llm.anthropic.AnthropicBedrock") as mock_bedrock:
            mock_bedrock.return_value = MagicMock()
            BedrockLLM()

        _, kwargs = mock_bedrock.call_args
        assert kwargs["aws_region"] == "us-east-1"

    def test_explicit_region_param_wins_over_everything(self, monkeypatch) -> None:
        monkeypatch.setenv("CUSTOS_BEDROCK_REGION", "eu-west-1")

        with patch("custos.llm.anthropic.AnthropicBedrock") as mock_bedrock:
            mock_bedrock.return_value = MagicMock()
            BedrockLLM(region="us-west-2")

        _, kwargs = mock_bedrock.call_args
        assert kwargs["aws_region"] == "us-west-2"


class TestBedrockLLMNoCredentials:
    """No LLM credential is ever passed to the Bedrock client constructor.

    This is the load-bearing security property of the whole Bedrock path:
    the SDK must resolve credentials through the standard boto3 chain (the
    ECS task role in production), never through an explicit key passed by
    this code. Passing one here would put an LLM credential back into the
    deployment, defeating the reason Bedrock mode exists.
    """

    def test_no_credential_kwargs_passed_to_constructor(self, monkeypatch) -> None:
        monkeypatch.delenv("CUSTOS_BEDROCK_REGION", raising=False)
        monkeypatch.delenv("AWS_REGION", raising=False)

        with patch("custos.llm.anthropic.AnthropicBedrock") as mock_bedrock:
            mock_bedrock.return_value = MagicMock()
            BedrockLLM()

        args, kwargs = mock_bedrock.call_args
        assert args == ()
        assert set(kwargs) == {"aws_region"}
        forbidden_keys = {
            "aws_access_key",
            "aws_secret_key",
            "aws_session_token",
            "api_key",
        }
        assert forbidden_keys.isdisjoint(kwargs)


class TestBedrockLLMGenerate:
    """BedrockLLM must be indistinguishable from ClaudeLLM to callers."""

    def test_empty_context_returns_refusal(self) -> None:
        llm = BedrockLLM.__new__(BedrockLLM)
        answer = llm.generate(
            system_prompt="test",
            context_chunks=[],
            user_query="What is the PTO policy?",
        )
        assert answer.refused is True
        assert len(answer.citations) == 0
        assert "don't have information" in answer.text.lower()

    def test_generate_resolves_citations_like_claude_llm(self, monkeypatch) -> None:
        monkeypatch.delenv("CUSTOS_BEDROCK_REGION", raising=False)
        monkeypatch.delenv("AWS_REGION", raising=False)

        mock_client = MagicMock()
        mock_client.messages.create.return_value = MagicMock(
            content=[
                MagicMock(
                    text='The PTO policy is generous. '
                    '```citations\n["chunk_1"]\n```'
                )
            ]
        )

        with patch("custos.llm.anthropic.AnthropicBedrock", return_value=mock_client):
            llm = BedrockLLM()

        chunk = _make_chunk("chunk_1", "doc-1", "PTO policy text.")
        answer = llm.generate(
            system_prompt="System instructions.",
            context_chunks=[chunk],
            user_query="What is the PTO policy?",
        )

        assert answer.refused is False
        assert len(answer.citations) == 1
        assert answer.citations[0].doc_id == "doc-1"
        assert mock_client.messages.create.call_count == 1
