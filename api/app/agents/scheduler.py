import uuid
from datetime import date as Date, datetime, timedelta
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field

from ..db.connection import get_conn
from .base import BaseAgent


class AppointmentStatus(str, Enum):
    scheduled = "scheduled"
    completed = "completed"
    cancelled = "cancelled"


class SearchAppointmentsArgs(BaseModel):
    query:          Optional[str]               = Field(None, description="Text to search: patient name, provider, or procedure")
    date_from:      Optional[str]               = Field(None, description="Start date inclusive (YYYY-MM-DD). Only set if the user explicitly mentions a date or range.")
    date_to:        Optional[str]               = Field(None, description="End date inclusive (YYYY-MM-DD). Only set if the user explicitly mentions a date or range.")
    status:         Optional[AppointmentStatus] = Field(None, description="Only set if the user explicitly requests a specific status.")
    patient_id:     Optional[str]               = Field(None, description="Filter by exact patient ID (e.g. P-1001)")
    procedure_code: Optional[str]               = Field(None, description="Filter by procedure code (e.g. D2391)")
    time_from:      Optional[str]               = Field(None, description="Start time inclusive (HH:MM), 24h format")
    time_to:        Optional[str]               = Field(None, description="End time inclusive (HH:MM), 24h format")


class ConfirmAppointmentArgs(BaseModel):
    patient_name:   str            = Field(..., description="Full name of the patient")
    patient_id:     str            = Field(..., description="Patient ID (e.g. P-1001)")
    provider:       str            = Field(..., description="Provider name (e.g. Dr. Reyes)")
    date:           str            = Field(..., description="Date (YYYY-MM-DD)")
    time:           str            = Field(..., description="Time (HH:MM)")
    procedure_desc: Optional[str]  = Field(None, description="Procedure description")
    duration_minutes: Optional[int] = Field(60, description="Duration in minutes")
    notes:          Optional[str]  = Field(None, description="Additional notes")


class DraftAppointmentArgs(BaseModel):
    patient_name:   str            = Field(..., description="Full name of the patient")
    patient_id:     str            = Field(..., description="Patient ID (e.g. P-1001)")
    provider:       str            = Field(..., description="Provider name (e.g. Dr. Reyes)")
    date:           str            = Field(..., description="Proposed date (YYYY-MM-DD)")
    time:           str            = Field(..., description="Proposed time (HH:MM)")
    procedure_desc: Optional[str]  = Field(None, description="Procedure description")
    notes:          Optional[str]  = Field(None, description="Additional notes")


class GetAvailableSlotsArgs(BaseModel):
    provider:         str           = Field(..., description="Provider name (e.g. Dr. Reyes)")
    date:             str           = Field(..., description="Date to check (YYYY-MM-DD)")
    duration_minutes: Optional[int] = Field(60, description="Duration needed in minutes (default 60)")


# Provider working schedules
_PROVIDER_SCHEDULES = {
    "Dr. Reyes": {"days": [0, 1, 2, 3, 4], "start": "08:00", "end": "17:00"},
    "Dr. Patel": {"days": [1, 2, 3, 4, 5], "start": "09:00", "end": "16:00"},
}

_SLOT_GRID_MINUTES = 15   # slot generation increment
_BUFFER_MINUTES    = 15   # between appointments


def _tool(name: str, description: str, model: type[BaseModel]) -> dict:
    schema = model.model_json_schema()
    schema.pop("title", None)
    return {"type": "function", "name": name, "description": description, "parameters": schema}


_VALID_APPOINTMENT_STATUSES = {s.value for s in AppointmentStatus}


class SchedulerAgent(BaseAgent):

    def __init__(self, tenant_id: str, session: dict | None = None):
        super().__init__(tenant_id)
        self.session = session or {}

    def prompt(self) -> str:
        now   = datetime.now()
        role  = self.session.get("role", "staff")
        clinic = self.session.get("tenant_name") or self.tenant_id
        patient_name = self.session.get("patient_name")

        if role == "patient":
            return (
                f"Today is {now.strftime('%A, %B %d, %Y')} and the current time is {now.strftime('%H:%M')}.\n\n"
                f"You are speaking with {patient_name}, a patient at {clinic}. "
                "You can only show this patient their own appointments. "
                "You cannot book, modify, or cancel appointments — direct the patient to call the clinic for any changes.\n\n"
                "You have access to one tool:\n"
                "- search_appointments: view this patient's own appointments\n\n"
                "Rules:\n"
                "1. Only retrieve data for this patient. Never show other patients' records.\n"
                "2. Every response must end with a 'Sources:' line."
            )

        return (
            f"Today is {now.strftime('%A, %B %d, %Y')} and the current time is {now.strftime('%H:%M')}.\n\n"
            f"You are a scheduling assistant at {clinic}. "
            "You help check appointment availability and book new appointments.\n\n"
            "You have access to four tools:\n"
            "- search_appointments: check existing appointments\n"
            "- get_available_slots: compute free slots for a provider on a date\n"
            "- draft_appointment: propose an appointment for review (does not save)\n"
            "- confirm_appointment: save the appointment to the database after user confirms\n\n"
            "Rules you must follow:\n"
            "1. Always call get_available_slots before drafting.\n"
            "2. Never double-book a provider.\n"
            "2a. If the requested provider is unavailable at a specific requested time, call get_available_slots for the other provider on the same date and check if that exact time is in their available slots. Only report whether that specific time is free — do not show full availability.\n"
            "3. When showing available slots, always format them as an ASCII table grouped by Morning and Afternoon:\n"
            "   ┌───────────┬──────────────────────────────────┐\n"
            "   │ Morning   │ 08:00                            │\n"
            "   │ Afternoon │ 11:45  12:00  12:15  13:00  ...  │\n"
            "   └───────────┴──────────────────────────────────┘\n"
            "   Only add a <select> block for time slots when you are about to call draft_appointment and need the user to confirm which slot to book. Never add <select> for informational availability checks.\n"
            "   <select>08:00,11:45,12:00,12:15</select>\n"
            "4. After showing a draft, always end with:\n"
            "   <select>Confirm,Cancel</select>\n"
            "   If user selects 'Confirm', call confirm_appointment with the same details.\n"
            "   If user selects 'Cancel', stop and acknowledge.\n"
            "5. When confirmed, include the appointment_id prominently in the response (e.g. 'Appointment ID: APT-XXXXXX').\n"
            "6. Every response must end with a 'Sources:' line."
        )

    def tools(self) -> list[dict]:
        if self.session.get("role") == "patient":
            return [
                _tool(
                    "search_appointments",
                    "View this patient's own appointments only.",
                    SearchAppointmentsArgs,
                ),
            ]
        return [
            _tool(
                "search_appointments",
                "Search existing appointments to check provider availability and patient history. "
                "Use date_from and date_to to find open slots. All dates must be YYYY-MM-DD.",
                SearchAppointmentsArgs,
            ),
            _tool(
                "get_available_slots",
                "Get available appointment slots for a provider on a specific date. "
                "Always call this before draft_appointment to present valid options to the user.",
                GetAvailableSlotsArgs,
            ),
            _tool(
                "draft_appointment",
                "Draft a new appointment proposal after confirming the slot is available. "
                "Does not persist — presents the draft for user confirmation.",
                DraftAppointmentArgs,
            ),
            _tool(
                "confirm_appointment",
                "Save a confirmed appointment to the database after the user has approved the draft. "
                "Only call this after the user explicitly confirms the proposed appointment.",
                ConfirmAppointmentArgs,
            ),
        ]

    def _execute(self, name: str, args: dict) -> list:
        if self.session.get("role") == "patient" and self.session.get("patient_id"):
            if name == "search_appointments":
                args["patient_id"] = self.session["patient_id"]
        if name == "search_appointments":
            return self._search_appointments(**args)
        if name == "get_available_slots":
            return self._get_available_slots(**args)
        if name == "draft_appointment":
            return self._draft_appointment(**args)
        if name == "confirm_appointment":
            return self._confirm_appointment(**args)
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
                   status, duration_minutes, notes
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

    def _get_available_slots(
        self,
        provider: str,
        date: str,
        duration_minutes: int = 60,
    ) -> list[dict]:
        schedule = _PROVIDER_SCHEDULES.get(provider)
        if not schedule:
            return [{"error": f"Unknown provider '{provider}'. Known providers: {list(_PROVIDER_SCHEDULES.keys())}"}]

        try:
            target = Date.fromisoformat(date)
        except ValueError:
            return [{"error": f"Invalid date '{date}'. Use YYYY-MM-DD."}]

        if target.weekday() not in schedule["days"]:
            day_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
            works = [day_names[d] for d in schedule["days"]]
            return [{"error": f"{provider} does not work on {target.strftime('%A')}. Works: {', '.join(works)}."}]

        # fetch existing appointments with duration
        conn = get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT time::text, duration_minutes FROM appointments
                    WHERE tenant_id = %s AND provider = %s AND date = %s AND status = 'scheduled'
                    ORDER BY time
                    """,
                    (self.tenant_id, provider, date),
                )
                existing = [{"time": r[0], "duration": r[1]} for r in cur.fetchall()]
        finally:
            conn.close()

        # build busy blocks (with buffer)
        day = datetime.fromisoformat(date)
        busy = []
        for appt in existing:
            h, m = int(appt["time"][:2]), int(appt["time"][3:5])
            start = day.replace(hour=h, minute=m)
            end   = start + timedelta(minutes=appt["duration"] + _BUFFER_MINUTES)
            busy.append((start, end))

        schedule_start = day.replace(hour=int(schedule["start"][:2]), minute=0)
        schedule_end   = day.replace(hour=int(schedule["end"][:2]),   minute=0)

        # find free windows and generate slots
        slots = []
        boundaries = [schedule_start] + [e for _, e in busy] + [schedule_end]
        windows = [(boundaries[i], min(s, schedule_end)) for i, (s, _) in enumerate(busy, 1)]
        windows.append((boundaries[-2] if busy else schedule_start, schedule_end))

        # simpler: walk grid and check conflicts
        current = schedule_start
        while current + timedelta(minutes=duration_minutes) <= schedule_end:
            slot_end = current + timedelta(minutes=duration_minutes)
            conflict = any(current < b_end and slot_end > b_start for b_start, b_end in busy)
            if not conflict:
                slots.append(current.strftime("%H:%M"))
            current += timedelta(minutes=_SLOT_GRID_MINUTES)

        morning   = [s for s in slots if int(s[:2]) < 12]
        afternoon = [s for s in slots if int(s[:2]) >= 12]

        return [{
            "provider":       provider,
            "date":           date,
            "duration_min":   duration_minutes,
            "morning":        morning,
            "afternoon":      afternoon,
            "total_available": len(slots),
            "_citation":      f"schedule/{provider}/{date}",
        }]

    def _draft_appointment(
        self,
        patient_name: str,
        patient_id: str,
        provider: str,
        date: str,
        time: str,
        procedure_desc: str | None = None,
        notes: str | None = None,
    ) -> list[dict]:
        draft = {
            "status":         "draft",
            "patient_name":   patient_name,
            "patient_id":     patient_id,
            "provider":       provider,
            "date":           date,
            "time":           time,
            "procedure_desc": procedure_desc or "",
            "notes":          notes or "",
            "tenant_id":      self.tenant_id,
            "_citation":      f"draft (appointments/{self.tenant_id})",
        }
        return [draft]

    def _confirm_appointment(
        self,
        patient_name: str,
        patient_id: str,
        provider: str,
        date: str,
        time: str,
        procedure_desc: str | None = None,
        duration_minutes: int = 60,
        notes: str | None = None,
    ) -> list[dict]:
        appointment_id = f"APT-{uuid.uuid4().hex[:6].upper()}"
        conn = get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO appointments (
                        appointment_id, patient_name, patient_id, provider,
                        date, time, procedure_desc, duration_minutes,
                        status, notes, tenant_id
                    ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'scheduled',%s,%s)
                    """,
                    (
                        appointment_id, patient_name, patient_id, provider,
                        date, time, procedure_desc or "", duration_minutes,
                        notes or "", self.tenant_id,
                    ),
                )
            conn.commit()
        finally:
            conn.close()

        return [{
            "status":         "confirmed",
            "appointment_id": appointment_id,
            "patient_name":   patient_name,
            "provider":       provider,
            "date":           date,
            "time":           time,
            "procedure_desc": procedure_desc or "",
            "_citation":      f"{appointment_id} (appointments/{self.tenant_id})",
        }]


def _valid_date(value: str) -> bool:
    try:
        Date.fromisoformat(value)
        return True
    except ValueError:
        return False
