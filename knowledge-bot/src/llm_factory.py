"""
llm_factory.py — Centralized factory for LLM instances.

WHAT THIS FILE DOES:
    Provides a single place to instantiate the correct LLM
    (OpenAI or Mistral) based on the environment configuration.
    
WHY THIS EXISTS (Factory Pattern):
    Previously, every module checked `LLM_PROVIDER` and initialized
    ChatOpenAI or ChatMistralAI. This led to code duplication and
    hardcoded dependencies. The factory pattern abstract this logic.
"""

from src.config import LLM_PROVIDER, MISTRAL_API_KEY, OPENAI_API_KEY, LLM_MODEL

def get_llm(temperature: float = 0.0, max_tokens: int = 1024, model: str = None, streaming: bool = False):
    """
    Instantiate and return the configured language model.
    """
    model = model or LLM_MODEL
    
    if LLM_PROVIDER == "mistral":
        from langchain_mistralai import ChatMistralAI
        return ChatMistralAI(
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            mistral_api_key=MISTRAL_API_KEY,
        )
    else:
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            openai_api_key=OPENAI_API_KEY,
            streaming=streaming,
        )
