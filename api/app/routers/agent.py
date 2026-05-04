import json
import logging
import time
import traceback

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from ..agents.scheduler import SchedulerAgent
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

    history = get_history(body.session_id)
    history.append({"role": "user", "content": body.query})

    session  = get_session(body.session_id)
    agent    = SchedulerAgent(tenant_id=tenant_id, session=session)
    stream, citations = agent.run(history)

    def event_stream():
        answer = ""
        try:
            for chunk in stream:
                answer += chunk
                yield f"data: {json.dumps({'type': 'token', 'value': chunk})}\n\n"
        except Exception:
            log.error(f"[agent] stream error:\n{traceback.format_exc()}")
            yield f"data: {json.dumps({'type': 'error', 'value': 'An error occurred. Check server logs.'})}\n\n"
        finally:
            latency = round(time.perf_counter() - started, 3)
            in_tok  = agent.usage["input_tokens"]
            out_tok = agent.usage["output_tokens"]
            cost    = round((in_tok * _COST_INPUT + out_tok * _COST_OUTPUT) / 1_000_000, 6)
            log.info(f"[agent] done session={body.session_id} latency={latency}s tokens=({in_tok}in/{out_tok}out) cost=${cost}")

            try:
                messages = (
                    [{"role": "user", "content": body.query}]
                    + agent.tool_messages
                    + [{"role": "assistant", "content": answer}]
                )
                append_messages(body.session_id, messages)
            except Exception:
                log.error("[agent] failed to save messages", exc_info=True)

            yield f"data: {json.dumps({'type': 'citations', 'value': citations})}\n\n"
            yield "data: [DONE]\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")
