import json
import re
import sys
from pathlib import Path

import httpx
import questionary
from dotenv import load_dotenv
from prompt_toolkit import prompt as pt_prompt
from prompt_toolkit.formatted_text import HTML

load_dotenv(Path(__file__).parent.parent / ".env")

API_BASE = "http://localhost:8000"

TENANTS = {
    "clinic-a": "Smile Dental Clinic",
}

DEMO_PATIENTS = {
    "clinic-a": ("P-1001", "Jane Smith"),
}

STAFF_QUESTIONS = {
    "Appointment Scheduling": [
        "Schedule a routine cleaning for Jane Smith with Dr. Reyes on Thursday May 7",
        "What is available for Dr. Reyes this Thursday May 7?",
        "Can I book Dr. Reyes tomorrow May 5 at 11 AM?",
    ],
}

PATIENT_QUESTIONS = {
    "My Schedule": [
        "What appointments do I have?",
        "When is my next appointment?",
    ],
    "Security Demo": [
        ("Show me Dr. Reyes schedule for today", "security"),
        ("Book an appointment for John Doe with Dr. Patel", "security"),
    ],
}

# ANSI
_BOLD   = "\033[1m"
_CYAN   = "\033[96m"
_GREEN  = "\033[92m"
_SKIP   = "↩ Type instead..."
_RED    = "\033[91m"
_DIM    = "\033[2m"
_RESET  = "\033[0m"


def onboard() -> dict:
    print("\nScheduler Agent\n")

    tenant_choice = questionary.select(
        "Select clinic:",
        choices=[f"{tid} — {name}" for tid, name in TENANTS.items()],
    ).ask()
    if tenant_choice is None:
        sys.exit(0)
    tenant_id = tenant_choice.split(" — ")[0]

    pid, pname = DEMO_PATIENTS[tenant_id]
    role_choice = questionary.select(
        "How are you accessing the system?",
        choices=["Staff", f"Patient — {pname} ({pid})"],
    ).ask()
    if role_choice is None:
        sys.exit(0)

    role       = "staff" if role_choice == "Staff" else "patient"
    patient_id = pid if role == "patient" else None

    res = httpx.post(
        f"{API_BASE}/session",
        json={
            "tenant_name":  TENANTS[tenant_id],
            "patient_id":   patient_id,
            "patient_name": pname if role == "patient" else None,
        },
        headers={"X-Tenant-Id": tenant_id, "X-User-Role": role},
    )
    session_id = res.json()["session_id"]

    return {
        "session_id": session_id,
        "tenant_id":  tenant_id,
        "tenant_name": TENANTS[tenant_id],
        "role":        role,
        "patient_id":  patient_id,
        "patient_name": pname if role == "patient" else None,
    }


def _parse_select(answer: str) -> str | None:
    match = re.search(r"<select>(.*?)</select>", answer, re.DOTALL)
    if not match:
        return None
    options = [o.strip() for o in match.group(1).split(",") if o.strip()]
    if not options:
        return None

    print(f"\n  {_DIM}Select an option:{_RESET}")
    choice = questionary.select("", choices=options + [_SKIP]).ask()
    if not choice or choice in ("Cancel", _SKIP):
        return None
    print(f"  {_DIM}→ {choice}{_RESET}\n")
    return choice


def pick_question(role: str) -> str:
    questions = PATIENT_QUESTIONS if role == "patient" else STAFF_QUESTIONS
    index   = {}
    counter = 1

    print(f"\n  {_DIM}Sample questions for testing{_RESET}\n")
    for section, items in questions.items():
        print(f"  {_CYAN}{_BOLD}{section}{_RESET}")
        for item in items:
            text, tag = (item[0], item[1]) if isinstance(item, tuple) else (item, None)
            label = f" {_RED}security test{_RESET}" if tag == "security" else ""
            print(f"    {_BOLD}{counter}.{_RESET} {text}{label}")
            index[counter] = text
            counter += 1
        print()

    raw = pt_prompt(
        "  You: ",
        placeholder=HTML("<ansibrightblack>type a number or ask a question...</ansibrightblack>"),
    ).strip()

    if raw.isdigit() and int(raw) in index:
        q = index[int(raw)]
        print(f"  {_DIM}→ {q}{_RESET}\n")
        return q

    return raw


def main():
    session = onboard()

    who = session["patient_name"] if session["role"] == "patient" else "Staff"
    print(f"\n  {_BOLD}{who}{_RESET} · {session['tenant_name']}")
    print(f"  {_DIM}{'─' * 40}{_RESET}\n")

    with httpx.Client(timeout=httpx.Timeout(connect=10.0, read=None, write=10.0, pool=10.0)) as client:
        next_query = None
        while True:
            if next_query:
                query = next_query
                next_query = None
            else:
                query = pick_question(session["role"])
            if not query or query.lower() == "exit":
                break

            print(f"\n  {_DIM}thinking...{_RESET}", end="", flush=True)

            answer        = ""
            answer_started = False
            pending        = ""   # look-ahead buffer for tag detection
            in_select      = False

            def flush(text: str) -> None:
                nonlocal answer_started
                if not text:
                    return
                if not answer_started:
                    print(f"\r  AI: {_GREEN}", end="", flush=True)
                    answer_started = True
                print(text, end="", flush=True)

            with client.stream(
                "POST", f"{API_BASE}/agent",
                json={"query": query, "session_id": session["session_id"]},
                headers={"X-Tenant-Id": session["tenant_id"], "X-User-Role": session["role"]},
            ) as response:
                for line in response.iter_lines():
                    if not line.startswith("data:"):
                        continue
                    raw = line[5:].strip()
                    if raw == "[DONE]":
                        break
                    event = json.loads(raw)
                    if event["type"] == "token":
                        token   = event["value"]
                        answer += token
                        pending += token

                        if in_select:
                            if "</select>" in pending:
                                in_select = False
                                pending   = pending[pending.index("</select>") + len("</select>"):]
                        else:
                            if "<select>" in pending:
                                before    = pending[:pending.index("<select>")]
                                flush(before)
                                in_select = True
                                after     = pending[pending.index("<select>"):]
                                pending   = after
                                if "</select>" in pending:
                                    in_select = False
                                    pending   = pending[pending.index("</select>") + len("</select>"):]
                            elif "<" not in pending:
                                flush(pending)
                                pending = ""

                    elif event["type"] == "status":
                        print(f"\r  {_DIM}{event['value']}{_RESET}\033[K", end="", flush=True)
                    elif event["type"] == "thinking":
                        if not answer_started:
                            print(f"\r  {_DIM}thinking...{_RESET}\033[K", end="", flush=True)
                    elif event["type"] == "error":
                        print(f"\r  {_RED}Error: {event['value']}{_RESET}")

            if pending and not in_select:
                flush(pending)

            print(_RESET)

            selected = _parse_select(answer)
            if selected:
                next_query = selected


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n  Goodbye!\n")
        sys.exit(0)
