import numpy as np

from ..db.connection import get_conn
from ..ingest.embeddings import embed

_RRF_K = 60  # RRF constant — higher = smoother rank fusion


def vector_search(query: str, tenant_id: str, top_k: int = 10, document_id: str | None = None) -> list[dict]:
    vec = np.array(embed([query])[0], dtype=np.float32)
    extra = "AND document_id = %s" if document_id else ""
    sql = f"""
        SELECT text, source, document_id, page, chunk_index, doc_type,
               1 - (embedding <=> %s) AS score
        FROM data_sources
        WHERE tenant_id = %s {extra}
        ORDER BY embedding <=> %s
        LIMIT %s
    """
    params = [vec, tenant_id] + ([document_id] if document_id else []) + [vec, top_k]
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return _rows(cur)
    finally:
        conn.close()


def lexical_search(query: str, tenant_id: str, top_k: int = 10, document_id: str | None = None) -> list[dict]:
    extra = "AND document_id = %s" if document_id else ""
    sql = f"""
        SELECT text, source, document_id, page, chunk_index, doc_type,
               ts_rank(search_vector, websearch_to_tsquery('english', %s)) AS score
        FROM data_sources
        WHERE tenant_id = %s
          AND search_vector @@ websearch_to_tsquery('english', %s)
          {extra}
        ORDER BY score DESC
        LIMIT %s
    """
    params = [query, tenant_id, query] + ([document_id] if document_id else []) + [top_k]
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return _rows(cur)
    finally:
        conn.close()


def hybrid_search(query: str, tenant_id: str, top_k: int = 10, document_id: str | None = None) -> list[dict]:
    vector_results  = vector_search(query, tenant_id, top_k, document_id)
    lexical_results = lexical_search(query, tenant_id, top_k, document_id)

    rrf_scores: dict[str, float] = {}
    merged: dict[str, dict] = {}

    for rank, result in enumerate(vector_results):
        key = _key(result)
        rrf_scores[key] = rrf_scores.get(key, 0) + 1 / (_RRF_K + rank + 1)
        merged[key] = result

    for rank, result in enumerate(lexical_results):
        key = _key(result)
        rrf_scores[key] = rrf_scores.get(key, 0) + 1 / (_RRF_K + rank + 1)
        merged[key] = result

    ranked = sorted(rrf_scores.items(), key=lambda x: x[1], reverse=True)[:top_k]
    return [{**merged[k], "score": round(score, 6)} for k, score in ranked]


def _key(result: dict) -> str:
    return f"{result['source']}::{result['chunk_index']}"


def _rows(cur) -> list[dict]:
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]
