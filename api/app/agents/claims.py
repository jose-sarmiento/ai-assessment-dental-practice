from datetime import date as Date
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field

from ..db.connection import get_conn
from .base import BaseAgent


class ClaimStatus(str, Enum):
    pending = "pending"
    paid    = "paid"
    denied  = "denied"


class SearchClaimsArgs(BaseModel):
    query:          Optional[str]         = Field(None, description="Text to search: patient name, payer, or procedure")
    date_from:      Optional[str]         = Field(None, description="Start date of service inclusive (YYYY-MM-DD). Only set if the user explicitly mentions a date or range.")
    date_to:        Optional[str]         = Field(None, description="End date of service inclusive (YYYY-MM-DD). Only set if the user explicitly mentions a date or range.")
    status:         Optional[ClaimStatus] = Field(None, description="Only set if the user explicitly requests a specific status. Do not assume a default — omit to return all claims.")
    patient_id:     Optional[str]         = Field(None, description="Exact patient ID (e.g. P-1001)")
    procedure_code: Optional[str]         = Field(None, description="Procedure code (e.g. D1110)")
    payer:          Optional[str]         = Field(None, description="Insurance payer name")


_VALID_CLAIM_STATUSES = {s.value for s in ClaimStatus}


def _tool(name: str, description: str, model: type[BaseModel]) -> dict:
    schema = model.model_json_schema()
    schema.pop("title", None)
    return {"type": "function", "name": name, "description": description, "parameters": schema}


class ClaimsAgent(BaseAgent):

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
            scope    = f"Only retrieve claims that belong to {patient_name}. Do not surface any other patient's billing records."
        else:
            identity = f"You are assisting a staff member at {clinic}."
            scope    = "You have access to all claims within the clinic."

        return (
            f"Today is {now.strftime('%A, %B %d, %Y')} and the current time is {now.strftime('%H:%M')}.\n\n"
            f"{identity} {scope}\n\n"
            "You are a Billing & Claims specialist. You help look up insurance claims, coverage status, "
            "outstanding balances, denied claims, and claim follow-ups.\n\n"
            "You have access to one tool:\n"
            "- search_claims: look up billing and insurance claim records by patient, payer, status, procedure, or date range. "
            "Results include billed_amount, insurance_paid, and patient_owed fields.\n\n"
            "Rules you must follow:\n"
            "1. Always use a tool before answering. Never answer from your own knowledge.\n"
            "2. If the tools return no results, give a specific response rather than a generic message.\n"
            "3. If records were found, end your answer with a 'Sources:' line listing the claim IDs used. If no records were found, omit the Sources line.\n"
            "4. Do not infer, assume, or fill gaps with outside knowledge. Stick strictly to retrieved data.\n"
            "5. If the question is outside the scope of claims and billing, say so."
        )

    def tools(self) -> list[dict]:
        return [
            _tool(
                "search_claims",
                "Search insurance claims by patient, payer, procedure, date of service range, or status. "
                "Only set status if the user explicitly asks for a specific status. "
                "Do not assume a default status — omit it to return all claims.",
                SearchClaimsArgs,
            ),
        ]

    def _execute(self, name: str, args: dict) -> list:
        args = {k: v for k, v in args.items() if v != "" and v is not None}
        if self.session.get("role") == "patient" and self.session.get("patient_id"):
            args["patient_id"] = self.session["patient_id"]
        if name == "search_claims":
            return self._search_claims(**args)
        return []

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


def _valid_date(value: str) -> bool:
    try:
        Date.fromisoformat(value)
        return True
    except ValueError:
        return False
