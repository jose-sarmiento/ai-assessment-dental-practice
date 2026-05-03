import uuid
from pathlib import Path

from ...db.store import upsert_data_sources
from ..chunker import chunk
from ..embeddings import embed
from ..parsers import parse
from .base import BaseDriver


def _document_id() -> str:
    return f"doc_{uuid.uuid4()}"


class DataSourcesDriver(BaseDriver):

    def __init__(self, tenant_id: str, effective_date: str | None = None):
        super().__init__(tenant_id)
        self.effective_date = effective_date

    def ingest(self, file_path: Path) -> int:
        doc_type    = file_path.suffix.lstrip(".").lower()
        document_id = _document_id()

        print(f"[data_sources] parsing   {file_path.name} ({document_id})")
        document = parse(file_path)
        chunks = chunk(document)
        print(f"[data_sources] chunked   {len(chunks)} chunks")

        total_chunks = len(chunks)
        total_pages  = max((c["page"] for c in chunks), default=1)

        print(f"[data_sources] embedding {total_chunks} chunks ...")
        embeddings = embed([c["text"] for c in chunks])

        records = [
            {
                "text":           c["text"],
                "page":           c["page"],
                "chunk_index":    i,
                "source":         file_path.name,
                "document_id":    document_id,
                "tenant_id":      self.tenant_id,
                "doc_type":       doc_type,
                "effective_date": self.effective_date,
                "embedding":      vec,
                "metadata": {
                    "chunk_number": i + 1,
                    "total_chunks": total_chunks,
                    "total_pages":  total_pages,
                    "page":         c["page"],
                },
            }
            for i, (c, vec) in enumerate(zip(chunks, embeddings))
        ]

        upsert_data_sources(records)
        print(f"[data_sources] done      {file_path.name} → {total_chunks} chunks, {total_pages} pages")
        return total_chunks
