import os

from openai import OpenAI

_client = OpenAI()  # reads OPENAI_API_KEY from env
_MODEL = "text-embedding-3-small"
_BATCH_SIZE = int(os.getenv("EMBEDDING_BATCH_SIZE", 50))


def embed(texts: list[str]) -> list[list[float]]:
    """
    Embed a list of strings using OpenAI, batched at 100 per request.
    Returns embeddings in the same order as input.
    """
    results: list[list[float]] = []
    for batch in _batches(texts, _BATCH_SIZE):
        response = _client.embeddings.create(input=batch, model=_MODEL)
        # response.data is ordered to match input
        results.extend(item.embedding for item in response.data)
    return results


def _batches(items: list, size: int):
    for i in range(0, len(items), size):
        yield items[i : i + size]
