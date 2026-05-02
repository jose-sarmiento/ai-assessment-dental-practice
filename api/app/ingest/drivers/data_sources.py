from pathlib import Path

from ...db.store import upsert_data_sources
from ..chunker import chunk
from ..embeddings import embed
from ..parsers import parse
from .base import BaseDriver


class DataSourcesDriver(BaseDriver):

    def __init__(self, tenant_id: str, effective_date: str | None = None):
        super().__init__(tenant_id)
        self.effective_date = effective_date

    def ingest(self, file_path: Path) -> int:
        doc_type = file_path.suffix.lstrip(".").lower()  # e.g. "txt", "pdf", "csv"

        print(f"[data_sources] parsing   {file_path.name}")
        document = parse(file_path)
        chunks = chunk(document)
        print(f"[data_sources] chunked   {len(chunks)} chunks")

        print(f"[data_sources] embedding {len(chunks)} chunks ...")
        embeddings = embed([c["text"] for c in chunks])

        records = [
            {
                "text":           c["text"],
                "page":           c["page"],
                "chunk_index":    i,
                "source":         file_path.name,
                "tenant_id":      self.tenant_id,
                "doc_type":       doc_type,
                "effective_date": self.effective_date,
                "embedding":      vec,
            }
            for i, (c, vec) in enumerate(zip(chunks, embeddings))
        ]

        upsert_data_sources(records)
        print(f"[data_sources] done      {file_path.name} → {len(records)} chunks stored")
        return len(records)
