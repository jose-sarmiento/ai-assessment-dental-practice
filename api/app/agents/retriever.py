from datetime import date as Date

from ..db.connection import get_conn
from ..search.search import hybrid_search
from .base import BaseAgent

_VALID_APPOINTMENT_STATUSES = {"scheduled", "completed", "cancelled"}
_VALID_CLAIM_STATUSES = {"pending", "paid", "denied"}


class RetrieverAgent(BaseAgent):

    def prompt(self) -> str:
        from datetime import datetime
        now = datetime.now()
        return (
            f"Today is {now.strftime('%A, %B %d, %Y')} and the current time is {now.strftime('%H:%M')}.\n\n"
            "You are a dental practice assistant. You have access to three tools:\n"
            "- search_appointments: look up appointment records\n"
            "- search_claims: look up insurance claim records\n"
            "- search_knowledge: search policy documents and FAQs\n\n"
            "Rules you must follow:\n"
            "1. Always use a tool before answering. Never answer from your own knowledge.\n"
            "2. If the tools return no results, say: 'I could not find any information on that in the system.'\n"
            "3. Every successful answer must end with a 'Sources:' line listing the record IDs or documents used.\n"
            "4. Do not infer, assume, or fill gaps with outside knowledge. Stick strictly to retrieved data.\n"
            "5. If the question is outside the scope of appointments, claims, or practice documents, say so."
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
            },
            {
                "type": "function",
                "name": "search_claims",
                "description": (
                    "Search insurance claims by patient, payer, procedure, "
                    "date of service range, or status."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Text to search: patient name, payer, or procedure",
                        },
                        "date_from": {"type": "string", "description": "Start date of service inclusive (YYYY-MM-DD)"},
                        "date_to":   {"type": "string", "description": "End date of service inclusive (YYYY-MM-DD)"},
                        "status": {
                            "type": "string",
                            "enum": ["pending", "paid", "denied"],
                        },
                        "patient_id":     {"type": "string", "description": "Exact patient ID (e.g. P-1001)"},
                        "procedure_code": {"type": "string", "description": "Procedure code (e.g. D1110)"},
                        "payer":          {"type": "string", "description": "Insurance payer name"},
                    },
                },
            },
            {
                "type": "function",
                "name": "search_knowledge",
                "description": (
                    "Search the knowledge base for insurance policies, treatment FAQs, "
                    "and other documents. Use for general questions not covered by appointments or claims. "
                    "Pass the user's question exactly as asked — do not rephrase or expand it."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "The user's question verbatim",
                        },
                    },
                    "required": ["query"],
                },
            },
        ]

    def _execute(self, name: str, args: dict) -> list:
        if name == "search_appointments":
            return self._search_appointments(**args)
        if name == "search_claims":
            return self._search_claims(**args)
        if name == "search_knowledge":
            return self._search_knowledge(**args)
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

        if status and status in _VALID_APPOINTMENT_STATUSES:
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
                    row["_citation"] = row["appointment_id"]
                return rows
        finally:
            conn.close()

    def _search_claims(
        self,
        query: str = "",
        date_from: str | None = None,
        date_to: str | None = None,
        status: str | None = None,
        patient_id: str | None = None,
        procedure_code: str | None = None,
        payer: str | None = None,
    ) -> list[dict]:
        conditions = ["tenant_id = %s"]
        params: list = [self.tenant_id]

        if query:
            conditions.append("search_vector @@ websearch_to_tsquery('english', %s)")
            params.append(query)
        if date_from and _valid_date(date_from):
            conditions.append("date_of_service >= %s")
            params.append(date_from)
        if date_to and _valid_date(date_to):
            conditions.append("date_of_service <= %s")
            params.append(date_to)
        if status and status in _VALID_CLAIM_STATUSES:
            conditions.append("status = %s")
            params.append(status)
        if patient_id:
            conditions.append("patient_id = %s")
            params.append(patient_id)
        if procedure_code:
            conditions.append("procedure_code = %s")
            params.append(procedure_code.upper())
        if payer:
            conditions.append("payer ILIKE %s")
            params.append(f"%{payer}%")

        sql = f"""
            SELECT claim_id, patient_id, patient_name, date_of_service::text,
                   procedure_code, procedure_desc,
                   billed_amount::text, insurance_paid::text, patient_owed::text,
                   status, payer, notes
            FROM claims
            WHERE {" AND ".join(conditions)}
            ORDER BY date_of_service DESC
            LIMIT 20
        """
        conn = get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                cols = [d[0] for d in cur.description]
                rows = [dict(zip(cols, row)) for row in cur.fetchall()]
                for row in rows:
                    row["_citation"] = row["claim_id"]
                return rows
        finally:
            conn.close()

    def _search_knowledge(self, query: str) -> list[dict]:
        results = hybrid_search(query, self.tenant_id, top_k=5)
        for r in results:
            r["_citation"] = f"{r['source']} (p{r['page']})"
        return results


def _valid_date(value: str) -> bool:
    try:
        Date.fromisoformat(value)
        return True
    except ValueError:
        return False
