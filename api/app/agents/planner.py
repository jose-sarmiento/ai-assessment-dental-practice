_MODEL = "gpt-5.5"

from .base import BaseAgent
from .claims import ClaimsAgent
from .retriever import RetrieverAgent
from .scheduler import SchedulerAgent


class PlannerAgent(BaseAgent):

    def __init__(self, tenant_id: str, session: dict | None = None):
        super().__init__(tenant_id)
        self._model     = _MODEL
        self._reasoning = {"effort": "low"}
        self.session    = session or {}

    def prompt(self) -> str:
        from datetime import datetime
        now = datetime.now()

        role         = self.session.get("role", "staff")
        clinic       = self.session.get("tenant_name") or self.tenant_id
        patient_name = self.session.get("patient_name")
        patient_id   = self.session.get("patient_id")

        scope = "Data scoping and access control are enforced by the subagents — interpret and delegate requests correctly based on this context."

        if role == "patient" and patient_name:
            identity = f"You are speaking with {patient_name} (ID: {patient_id}), a patient at {clinic}."
        else:
            identity = f"You are assisting a staff member at {clinic}."

        return (
            f"Today is {now.strftime('%A, %B %d, %Y')} and the current time is {now.strftime('%H:%M')}.\n\n"
            f"{identity} {scope}\n\n"
            "You are an orchestration agent responsible for coordinating multiple specialized agents and tools.\n\n"
            "Your responsibilities:\n"
            "1. Understand the user's intent.\n"
            "2. Break complex requests into structured steps internally.\n"
            "3. Select the best agent/tool for each step.\n"
            "4. Execute steps in the correct order.\n"
            "5. Maintain context across steps.\n"
            "6. Return a final, coherent response.\n\n"
            "AVAILABLE TOOLS:\n"
            "- appointment_scheduler → viewing appointments, appointment history, booking, availability, slot lookup, cancellations\n"
            "- billing_claims → insurance claims, coverage status, outstanding balances, denied claims, claim follow-ups\n"
            "- knowledge_retriever → practice documents, policies, FAQs, treatment guidelines ONLY — not for appointments or claims\n\n"
            "STRICT RULES:\n"
            "- Do NOT hallucinate tools or agents.\n"
            "- Only use available tools when necessary.\n"
            "- If a request can be answered directly, do so without delegation.\n"
            "- If missing information, ask a clarifying question.\n"
            "- Prefer deterministic sources (retriever, DB) over guessing.\n"
            "- Never expose internal reasoning or planning steps.\n\n"
            "MULTI-AGENT STRATEGY:\n"
            "- Use specialized agents for domain-specific tasks.\n"
            "- If multiple steps are required:\n"
            "  1. Retrieve required information first\n"
            "  2. Then perform actions (e.g., scheduling)\n"
            "- Combine outputs into a single final response.\n"
            "- Do not call the same tool repeatedly with the same intent.\n\n"
            "EXECUTION BEHAVIOR:\n"
            "- Think step-by-step internally (do NOT output the plan).\n"
            "- Call tools when needed.\n"
            "- After each tool result:\n"
            "  → decide whether to continue OR finalize\n"
            "- If sufficient information is available:\n"
            "  → produce the final answer instead of calling another tool\n\n"
            "OUTPUT RULES:\n"
            "- Always return a clear, user-friendly answer.\n"
            "- Include 'Sources:' only if records were found or an action was taken. Omit it if nothing was found.\n"
            "- When the result from appointment_scheduler contains formatted tables, slot lists, or structured booking output, "
            "reproduce it exactly as returned — do not reformat, summarize, or paraphrase it. "
            "Preserve all ASCII tables, bullet lists, and <select> blocks verbatim."
        )

    def tools(self) -> list[dict]:
        return [
            {
                "type": "function",
                "name": "appointment_scheduler",
                "description": (
                    "Delegate to the scheduling agent. Use for: viewing appointments, appointment history, "
                    "booking appointments, checking provider availability, slot lookup, cancellation requests."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "The user's request verbatim"},
                    },
                    "required": ["query"],
                },
            },
            {
                "type": "function",
                "name": "billing_claims",
                "description": (
                    "Delegate to the Billing & Claims agent. Use for: insurance claims, coverage status, "
                    "outstanding balances (patient_owed), denied claims, claim follow-ups, billing queries."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "The user's request verbatim"},
                    },
                    "required": ["query"],
                },
            },
            {
                "type": "function",
                "name": "knowledge_retriever",
                "description": (
                    "Delegate to the knowledge retrieval agent. Use ONLY for: "
                    "practice documents, policies, FAQs, treatment guidelines, and knowledge base Q&A. "
                    "Do NOT use for appointments or claims — those have dedicated agents."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "The user's request verbatim"},
                    },
                    "required": ["query"],
                },
            },
        ]

    def _execute(self, name: str, args: dict) -> list:
        query = args.get("query", "")
        if name == "appointment_scheduler":
            return self._run_subagent(SchedulerAgent(self.tenant_id, self.session), query)
        if name == "billing_claims":
            return self._run_subagent(ClaimsAgent(self.tenant_id, self.session), query)
        if name == "knowledge_retriever":
            return self._run_subagent(RetrieverAgent(self.tenant_id, self.session), query)
        return []

    def _run_subagent(self, agent: BaseAgent, query: str) -> list[dict]:
        from .base import log as base_log
        from ..core.session import get_history, append_messages

        agent_key  = type(agent).__name__
        session_id = self.session.get("id")

        base_log.debug(f"[subagent] → {agent_key} query={query!r}")

        history = get_history(session_id, agent=agent_key)
        history.append({"role": "user", "content": query})

        stream = agent.run(history)
        text   = "".join(e["value"] for e in stream if e.get("type") == "token")

        base_log.debug(f"[subagent] ← {agent_key} result={text[:300]!r}")

        append_messages(
            session_id,
            [{"role": "user", "content": query}, *agent.tool_messages, {"role": "assistant", "content": text}],
            agent=agent_key,
        )

        self.usage["input_tokens"]  += agent.usage["input_tokens"]
        self.usage["output_tokens"] += agent.usage["output_tokens"]

        return [{"result": text, "agent": agent_key}]
