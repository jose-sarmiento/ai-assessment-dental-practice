import json
import logging
import time
import traceback

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from ..agents.planner import PlannerAgent
from ..core.deps import get_tenant_id, get_user_role
from ..core.session import append_messages, get_history, get_session

router = APIRouter()
log = logging.getLogger(__name__)

_COST_INPUT  = 2.00
_COST_OUTPUT = 8.00


class AgentRequest(BaseModel):
    query:      str
    session_id: str


@router.post("/agent")
async def agent_endpoint(
    body: AgentRequest,
    tenant_id: str = Depends(get_tenant_id),
    user_role: str = Depends(get_user_role),
):
    started = time.perf_counter()
    log.info(f"[agent] session={body.session_id} tenant={tenant_id} role={user_role}")

    history = get_history(body.session_id, agent="PlannerAgent")
    history.append({"role": "user", "content": body.query})

    session  = get_session(body.session_id)
    agent    = PlannerAgent(tenant_id=tenant_id, session=session)
    stream = agent.run(history)

    def event_stream():
        answer = ""
        error = False
        try:
            for event in stream:
                if event.get("type") == "token":
                    answer += event["value"]
                yield f"data: {json.dumps(event)}\n\n"
        except Exception:
            error = True
            log.error(f"[agent] stream error:\n{traceback.format_exc()}")
            yield f"data: {json.dumps({'type': 'error', 'value': 'An error occurred. Check server logs.'})}\n\n"
        finally:
            latency = round(time.perf_counter() - started, 3)
            in_tok  = agent.usage["input_tokens"]
            out_tok = agent.usage["output_tokens"]
            cost    = round((in_tok * _COST_INPUT + out_tok * _COST_OUTPUT) / 1_000_000, 6)
            log.info(f"[agent] done session={body.session_id} latency={latency}s tokens=({in_tok}in/{out_tok}out) cost=${cost}")

            log.debug(f"[answer] session={body.session_id} text={answer[:400]!r}")

            if not error:
                try:
                    messages = (
                        [{"role": "user", "content": body.query}]
                        + agent.tool_messages
                        + [{"role": "assistant", "content": answer}]
                    )
                    append_messages(body.session_id, messages, agent="PlannerAgent")
                except Exception:
                    log.error("[agent] failed to save messages", exc_info=True)

            yield "data: [DONE]\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")
