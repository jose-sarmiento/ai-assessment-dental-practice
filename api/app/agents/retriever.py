import re
from datetime import date as Date
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field

from ..db.connection import get_conn
from ..search.search import hybrid_search
from .base import BaseAgent


# ── Tool schemas ───────────────────────────────────────────────────────────────

class AppointmentStatus(str, Enum):
    scheduled = "scheduled"
    completed = "completed"
    cancelled = "cancelled"


class ClaimStatus(str, Enum):
    pending = "pending"
    paid    = "paid"
    denied  = "denied"


class SearchAppointmentsArgs(BaseModel):
    query:          Optional[str]               = Field(None, description="Text to search: patient name, provider, or procedure")
    date_from:      Optional[str]               = Field(None, description="Start date inclusive (YYYY-MM-DD). Only set if the user explicitly mentions a date or range.")
    date_to:        Optional[str]               = Field(None, description="End date inclusive (YYYY-MM-DD). Only set if the user explicitly mentions a date or range.")
    status:         Optional[AppointmentStatus] = Field(None, description="Only set if the user explicitly requests a specific status.")
    patient_id:     Optional[str]               = Field(None, description="Filter by exact patient ID (e.g. P-1001)")
    procedure_code: Optional[str]               = Field(None, description="Filter by procedure code (e.g. D2391)")
    time_from:      Optional[str]               = Field(None, description="Start time inclusive (HH:MM), 24h format")
    time_to:        Optional[str]               = Field(None, description="End time inclusive (HH:MM), 24h format")


class SearchClaimsArgs(BaseModel):
    query:          Optional[str]         = Field(None, description="Text to search: patient name, payer, or procedure")
    date_from:      Optional[str]         = Field(None, description="Start date of service inclusive (YYYY-MM-DD). Only set if the user explicitly mentions a date or range.")
    date_to:        Optional[str]         = Field(None, description="End date of service inclusive (YYYY-MM-DD). Only set if the user explicitly mentions a date or range.")
    status:         Optional[ClaimStatus] = Field(None, description="Only set if the user explicitly requests a specific status. Do not assume a default — omit to return all claims.")
    patient_id:     Optional[str]         = Field(None, description="Exact patient ID (e.g. P-1001)")
    procedure_code: Optional[str]         = Field(None, description="Procedure code (e.g. D1110)")
    payer:          Optional[str]         = Field(None, description="Insurance payer name")


class SearchKnowledgeArgs(BaseModel):
    query: str = Field(..., description="The user's question verbatim")


class SearchInDocumentArgs(BaseModel):
    document_id: str = Field(..., description="The document_id field from search results — stored as doc_[uuid] format (e.g. doc_3f2a1b4c-...). Do NOT use the source/filename.")
    query:       str = Field(..., description="The user's question verbatim")


class ReadDocumentArgs(BaseModel):
    document_id: str           = Field(..., description="The document_id field from search results — stored as doc_[uuid] format (e.g. doc_3f2a1b4c-...). Do NOT use the source/filename.")
    page:        Optional[int] = Field(None, description="Read all chunks for a specific page number. Use this when the user asks to read or summarize a specific page.")
    chunk_from:  int           = Field(0,   description="Start chunk index (0-based, inclusive). Used when page is not set.")
    chunk_to:    int           = Field(5,   description="End chunk index (inclusive). Use metadata.total_chunks to know the range.")




_DOC_ID_PATTERN = re.compile(
    r"^doc_[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
)

def _invalid_doc_id(document_id: str) -> list[dict] | None:
    if not _DOC_ID_PATTERN.match(document_id):
        return [{"error": f"Invalid document_id '{document_id}'. Must be in doc_[uuid] format (e.g. doc_3f2a1b4c-9d2e-4a1b-8c7f-1234567890ab)."}]
    return None


# ── Agent ──────────────────────────────────────────────────────────────────────

def _tool(name: str, description: str, model: type[BaseModel]) -> dict:
    schema = model.model_json_schema()
    schema.pop("title", None)
    return {"type": "function", "name": name, "description": description, "parameters": schema}


_VALID_APPOINTMENT_STATUSES = {s.value for s in AppointmentStatus}
_VALID_CLAIM_STATUSES       = {s.value for s in ClaimStatus}


class RetrieverAgent(BaseAgent):

    def __init__(self, tenant_id: str, session: dict | None = None):
        super().__init__(tenant_id)
        self.session = session or {}

    def prompt(self) -> str:
        from datetime import datetime
        now = datetime.now()

        role         = self.session.get("role", "staff")
        clinic       = self.session.get("tenant_name") or self.tenant_id
        patient_name = self.session.get("patient_name")
        patient_id   = self.session.get("patient_id")

        if role == "patient" and patient_name:
            identity = f"You are speaking with {patient_name} (ID: {patient_id}), a patient at {clinic}."
            scope    = f"Only retrieve data that belongs to {patient_name}. Do not surface any other patient's records."
        else:
            identity = f"You are assisting a staff member at {clinic}."
            scope    = "You have access to all records within the clinic."

        return (
            f"Today is {now.strftime('%A, %B %d, %Y')} and the current time is {now.strftime('%H:%M')}.\n\n"
            f"{identity} {scope}\n\n"
            "You have access to the following tools:\n"
            "- search_appointments: look up appointment records\n"
            "- search_claims: look up insurance claim records\n"
            "- search_knowledge: global search across all knowledge base documents (FAQs, policies, guides). Use this first for any general question.\n"
            "- search_in_document: search within a specific document by document_id. Use this for follow-up questions when the user is already asking about a specific document returned by search_knowledge.\n"
            "- read_document: traverse and read chunks from a known document by document_id. Use this when the user wants to read a specific page, continue reading, or scroll through content across turns — not a one-shot full read.\n\n"
            "Rules you must follow:\n"
            "1. Always use a tool before answering. Never answer from your own knowledge.\n"
            "2. If the tools return no results, give a specific response rather than a generic message.\n"
            "3. Every successful answer must end with a 'Sources:' line listing the record IDs or documents used.\n"
            "4. Do not infer, assume, or fill gaps with outside knowledge. Stick strictly to retrieved data.\n"
            "5. If the question is outside the scope of appointments, claims, or practice documents, say so."
        )

    def tools(self) -> list[dict]:
        return [
            _tool(
                "search_appointments",
                "Search appointments by patient name, provider, procedure, date range, or status. "
                "Use date_from and date_to for ranges (e.g. a full month). All dates must be YYYY-MM-DD.",
                SearchAppointmentsArgs,
            ),
            _tool(
                "search_claims",
                "Search insurance claims by patient, payer, procedure, date of service range, or status. "
                "Only set status if the user explicitly asks for a specific status. "
                "Do not assume a default status — omit it to return all claims.",
                SearchClaimsArgs,
            ),
            _tool(
                "search_knowledge",
                "Search the knowledge base for insurance policies, treatment FAQs, and other documents. "
                "Use for general questions not covered by appointments or claims. "
                "Pass the user's question exactly as asked — do not rephrase or expand it.",
                SearchKnowledgeArgs,
            ),
            _tool(
                "search_in_document",
                "Search within a specific document by its document_id. "
                "Use after search_knowledge returns a relevant document and you need to find more specific content within it.",
                SearchInDocumentArgs,
            ),
            _tool(
                "read_document",
                "Read the actual content of a known document — use this to traverse or scroll through a document across multiple turns. "
                "Fetch all chunks of a specific page using the page parameter, or fetch a range of chunks using chunk_from/chunk_to. "
                "Each returned chunk includes metadata with total_chunks and total_pages so you always know your position. "
                "Use this when the user wants to read a specific page, continue reading, or access the full content of a document.",
                ReadDocumentArgs,
            ),
        ]

    def _execute(self, name: str, args: dict) -> list:
        args = {k: v for k, v in args.items() if v != "" and v is not None}
        if self.session.get("role") == "patient" and self.session.get("patient_id"):
            if name in ("search_appointments", "search_claims"):
                args["patient_id"] = self.session["patient_id"]
        if name == "search_appointments":
            return self._search_appointments(**args)
        if name == "search_claims":
            return self._search_claims(**args)
        if name == "search_knowledge":
            return self._search_knowledge(**args)
        if name == "search_in_document":
            return self._search_in_document(**args)
        if name == "read_document":
            return self._read_document(**args)
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
        results = hybrid_search(query, self.tenant_id, top_k=5, role=self.session.get("role", "staff"))
        for r in results:
            r["_citation"] = f"{r['source']} (p{r['page']})"
        return results

    def _search_in_document(self, document_id: str, query: str) -> list[dict]:
        if err := _invalid_doc_id(document_id):
            return err
        results = hybrid_search(query, self.tenant_id, top_k=5, document_id=document_id, role=self.session.get("role", "staff"))
        for r in results:
            r["_citation"] = f"{r['source']} (chunk {r['chunk_index']})"
        return results

    def _read_document(
        self,
        document_id: str,
        page: int | None = None,
        chunk_from: int = 0,
        chunk_to: int = 5,
    ) -> list[dict]:
        if err := _invalid_doc_id(document_id):
            return err
        if page is not None:
            sql = """
                SELECT text, source, document_id, page, chunk_index, metadata
                FROM data_sources
                WHERE tenant_id = %s AND document_id = %s AND page = %s
                ORDER BY chunk_index
            """
            params = (self.tenant_id, document_id, page)
        else:
            sql = """
                SELECT text, source, document_id, page, chunk_index, metadata
                FROM data_sources
                WHERE tenant_id = %s AND document_id = %s
                  AND chunk_index >= %s AND chunk_index <= %s
                ORDER BY chunk_index
            """
            params = (self.tenant_id, document_id, chunk_from, chunk_to)

        conn = get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                cols = [d[0] for d in cur.description]
                rows = [dict(zip(cols, row)) for row in cur.fetchall()]
                for row in rows:
                    row["_citation"] = f"{row['source']} (p{row['page']}, chunk {row['chunk_index']})"
                return rows
        finally:
            conn.close()


def _valid_date(value: str) -> bool:
    try:
        Date.fromisoformat(value)
        return True
    except ValueError:
        return False
