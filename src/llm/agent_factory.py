from llm.openai_client import OpenAIClient


def create_llm_client(provider: str, model: str | None = None):
    if provider == "openai":
        return OpenAIClient(model=model) if model else OpenAIClient()

    raise ValueError(f"Unsupported LLM provider: {provider}")