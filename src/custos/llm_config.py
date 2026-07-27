"""LLM provider selection.

CUSTOS_LLM_PROVIDER picks between "anthropic" (default, ClaudeLLM, calls
api.anthropic.com directly) and "bedrock" (BedrockLLM, calls Amazon Bedrock
over a VPC interface endpoint so the deployment needs no internet egress
and no LLM credential anywhere in its infrastructure). This module is the
only place provider-specific construction happens, matching the
CUSTOS_VECTOR_BACKEND / vector_store_config.py and CUSTOS_AGENT_RUNTIME /
agent_runtime.py pattern: callers (api.py, agent_loop.py, agent_runtime.py)
depend on the AnyLLM union, not on a concrete provider class.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from custos.llm import BedrockLLM, ClaudeLLM

if TYPE_CHECKING:
    from collections.abc import Callable

AnyLLM = ClaudeLLM | BedrockLLM

_PROVIDERS = ("anthropic", "bedrock")


def get_provider() -> str:
    """Return the configured provider name (CUSTOS_LLM_PROVIDER, default anthropic)."""
    return os.environ.get("CUSTOS_LLM_PROVIDER", "anthropic").strip().lower()


def get_llm(
    *,
    api_key: str | None = None,
    on_api_call: Callable[[], None] | None = None,
) -> AnyLLM:
    """Construct the LLM selected by CUSTOS_LLM_PROVIDER.

    Defaults to "anthropic" (ClaudeLLM) when unset, unchanged from prior
    behavior. "bedrock" selects BedrockLLM; api_key is ignored in that case
    since Bedrock authenticates via the boto3 credential chain, never an
    API key.
    """
    provider = get_provider()

    if provider == "anthropic":
        return ClaudeLLM(api_key=api_key, on_api_call=on_api_call)

    if provider == "bedrock":
        return BedrockLLM(on_api_call=on_api_call)

    raise ValueError(
        f"Unknown CUSTOS_LLM_PROVIDER={provider!r}; expected one of {_PROVIDERS}."
    )
