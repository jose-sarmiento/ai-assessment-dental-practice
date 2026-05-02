from datetime import date as Date

from ..db.connection import get_conn
from .base import BaseAgent

_VALID_STATUSES = {"scheduled", "completed", "cancelled"}


class RetrieverAgent(BaseAgent):

    def prompt(self) -> str:
        from datetime import datetime
        now = datetime.now()
        return (
            f"Today is {now.strftime('%A, %B %d, %Y')} and the current time is {now.strftime('%H:%M')}. "
            "You are a helpful assistant for a dental practice. "
            "Use the available tools to look up appointments, claims, and documents. "
            "Only answer from retrieved data — never guess. "
            "When you have enough information, respond directly to the user."
        )

    def tools(self) -> list[dict]:
        return [
            {
                "type": "function",
                "name": "search_appointments",
                "description": (
                    "Search appointments by patient name, provider, procedure, "
                    "date range, or status. Use date_from and date_to for ranges "
                    "(e.g. a full month). All dates must be YYYY-MM-DD."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Text to search: patient name, provider, or procedure",
                        },
                        "date_from": {
                            "type": "string",
                            "description": "Start date inclusive (YYYY-MM-DD)",
                        },
                        "date_to": {
                            "type": "string",
                            "description": "End date inclusive (YYYY-MM-DD)",
                        },
                        "status": {
                            "type": "string",
                            "enum": ["scheduled", "completed", "cancelled"],
                            "description": "Appointment status",
                        },
                        "patient_id": {
                            "type": "string",
                            "description": "Filter by exact patient ID (e.g. P-1001)",
                        },
                        "procedure_code": {
                            "type": "string",
                            "description": "Filter by procedure code (e.g. D2391)",
                        },
                        "time_from": {
                            "type": "string",
                            "description": "Start time inclusive (HH:MM), 24h format",
                        },
                        "time_to": {
                            "type": "string",
                            "description": "End time inclusive (HH:MM), 24h format",
                        },
                    },
                },
            }
        ]

    def _execute(self, name: str, args: dict) -> list:
        if name == "search_appointments":
            return self._search_appointments(**args)
        return []

    def _search_appointments(
        self,
        query: str = "",
        date_from: str | None = None,
        date_to: str | None = None,
        status: str | None = None,
        patient_id: str | None = None,
        procedure_code: str | None = None,
        time_from: str | None = None,
        time_to: str | None = None,
    ) -> list[dict]:
        conditions = ["tenant_id = %s"]
        params: list = [self.tenant_id]

        if query:
            conditions.append("search_vector @@ websearch_to_tsquery('english', %s)")
            params.append(query)

        if date_from and _valid_date(date_from):
            conditions.append("date >= %s")
            params.append(date_from)

        if date_to and _valid_date(date_to):
            conditions.append("date <= %s")
            params.append(date_to)

        if status and status in _VALID_STATUSES:
            conditions.append("status = %s")
            params.append(status)

        if patient_id:
            conditions.append("patient_id = %s")
            params.append(patient_id)

        if procedure_code:
            conditions.append("procedure_code = %s")
            params.append(procedure_code.upper())

        if time_from:
            conditions.append("time >= %s")
            params.append(time_from)

        if time_to:
            conditions.append("time <= %s")
            params.append(time_to)

        sql = f"""
            SELECT appointment_id, patient_name, patient_id, provider,
                   date::text, time::text, procedure_code, procedure_desc,
                   status, notes
            FROM appointments
            WHERE {" AND ".join(conditions)}
            ORDER BY date, time
            LIMIT 20
        """
        conn = get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                cols = [d[0] for d in cur.description]
                rows = [dict(zip(cols, row)) for row in cur.fetchall()]
                for row in rows:
                    self._citations.append(row["appointment_id"])
                return rows
        finally:
            conn.close()


def _valid_date(value: str) -> bool:
    try:
        Date.fromisoformat(value)
        return True
    except ValueError:
        return False
