import numpy as np

from ..db.connection import get_conn
from ..ingest.embeddings import embed

_RRF_K = 60  # RRF constant — higher = smoother rank fusion


def vector_search(query: str, tenant_id: str, top_k: int = 10) -> list[dict]:
    vec = np.array(embed([query])[0], dtype=np.float32)
    sql = """
        SELECT text, source, page, chunk_index,
               1 - (embedding <=> %s) AS score
        FROM data_sources
        WHERE tenant_id = %s
        ORDER BY embedding <=> %s
        LIMIT %s
    """
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, (vec, tenant_id, vec, top_k))
            return _rows(cur)
    finally:
        conn.close()


def lexical_search(query: str, tenant_id: str, top_k: int = 10) -> list[dict]:
    sql = """
        SELECT text, source, page, chunk_index,
               ts_rank(search_vector, websearch_to_tsquery('english', %s)) AS score
        FROM data_sources
        WHERE tenant_id = %s
          AND search_vector @@ websearch_to_tsquery('english', %s)
        ORDER BY score DESC
        LIMIT %s
    """
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, (query, tenant_id, query, top_k))
            return _rows(cur)
    finally:
        conn.close()


def hybrid_search(query: str, tenant_id: str, top_k: int = 10) -> list[dict]:
    vector_results  = vector_search(query, tenant_id, top_k)
    lexical_results = lexical_search(query, tenant_id, top_k)

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
