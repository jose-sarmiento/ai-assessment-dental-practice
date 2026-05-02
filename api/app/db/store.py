import numpy as np

from .connection import get_conn

_UPSERT_SQL = """
    INSERT INTO data_sources (
        text, embedding, tenant_id, doc_type, source, page, chunk_index, effective_date
    ) VALUES %s
    ON CONFLICT DO NOTHING
"""


def upsert_data_sources(records: list[dict]) -> None:
    if not records:
        return

    rows = [
        (
            rec["text"],
            np.array(rec["embedding"], dtype=np.float32),
            rec["tenant_id"],
            rec["doc_type"],
            rec["source"],
            rec["page"],
            rec["chunk_index"],
            rec.get("effective_date"),
        )
        for rec in records
    ]

    conn = get_conn()
    try:
        with conn.cursor() as cur:
            from psycopg2.extras import execute_values
            execute_values(cur, _UPSERT_SQL, rows)
        conn.commit()
        print(f"[db] stored {len(rows)} data_sources")
    finally:
        conn.close()
