from docling.chunking import HybridChunker
from docling.datamodel.document import DoclingDocument

_chunker = HybridChunker()


def chunk(document: DoclingDocument) -> list[dict]:
    """
    Returns list of {"text": str, "page": int} dicts.
    Page defaults to 1 when provenance is unavailable.
    """
    results = []
    for c in _chunker.chunk(document):
        text = _chunker.serialize(c)
        page = _get_page(c)
        results.append({"text": text, "page": page})
    return results


def _get_page(chunk) -> int:
    try:
        return chunk.meta.doc_items[0].prov[0].page_no
    except (AttributeError, IndexError):
        return 1
