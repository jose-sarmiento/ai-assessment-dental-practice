import json

from ..db.connection import get_conn


def create_session(
    session_id: str,
    tenant_id: str,
    tenant_name: str | None,
    role: str,
    patient_id: str | None = None,
    patient_name: str | None = None,
) -> None:
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO sessions (id, tenant_id, tenant_name, role, patient_id, patient_name)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (session_id, tenant_id, tenant_name, role, patient_id, patient_name),
            )
        conn.commit()
    finally:
        conn.close()


def get_session(session_id: str) -> dict | None:
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, tenant_id, tenant_name, role, patient_id, patient_name FROM sessions WHERE id = %s",
                (session_id,),
            )
            row = cur.fetchone()
            if not row:
                return None
            return {
                "id":           row[0],
                "tenant_id":    row[1],
                "tenant_name":  row[2],
                "role":         row[3],
                "patient_id":   row[4],
                "patient_name": row[5],
            }
    finally:
        conn.close()


def get_history(session_id: str) -> list[dict]:
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT role, content, data FROM messages WHERE session_id = %s ORDER BY id",
                (session_id,),
            )
            history = []
            for role, content, data in cur.fetchall():
                if data is not None:
                    history.append(data)
                else:
                    history.append({"role": role, "content": content})
            return history
    finally:
        conn.close()


def append_messages(session_id: str, messages: list[dict]) -> None:
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            for msg in messages:
                if "role" in msg:
                    cur.execute(
                        "INSERT INTO messages (session_id, role, content) VALUES (%s, %s, %s)",
                        (session_id, msg["role"], msg.get("content", "")),
                    )
                else:
                    cur.execute(
                        "INSERT INTO messages (session_id, data) VALUES (%s, %s)",
                        (session_id, json.dumps(msg)),
                    )
        conn.commit()
    finally:
        conn.close()
