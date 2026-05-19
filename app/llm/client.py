from __future__ import annotations

from langchain_openai import AzureChatOpenAI

from app.config import get_settings


def get_llm(temperature: float = 0.0, json_mode: bool = False) -> AzureChatOpenAI:
    """Return a configured AzureChatOpenAI instance.

    Single factory — never instantiate AzureChatOpenAI elsewhere.
    temperature > 0.0 requires a comment at the call site explaining why.
    """
    s = get_settings()
    kwargs: dict = dict(
        azure_endpoint=s.azure_openai_endpoint,
        api_key=s.azure_openai_key,
        azure_deployment=s.azure_openai_deployment,
        api_version=s.azure_openai_api_version,
        temperature=temperature,
    )
    if json_mode:
        kwargs["model_kwargs"] = {"response_format": {"type": "json_object"}}
    return AzureChatOpenAI(**kwargs)
