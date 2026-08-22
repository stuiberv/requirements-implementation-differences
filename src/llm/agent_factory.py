from llm.openai_client import OpenAIClient


def create_llm_client(provider: str):
    if provider == "openai":
        return OpenAIClient()

    raise ValueError(
        f"Unsupported LLM provider: {provider}"
    )