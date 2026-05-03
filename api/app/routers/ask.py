import json
import logging
import traceback

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from ..agents.retriever import RetrieverAgent
from ..core.deps import get_tenant_id, get_user_role
from ..core.session import append_messages, get_history, get_session

router = APIRouter()
log = logging.getLogger(__name__)


class AskRequest(BaseModel):
    query: str
    session_id: str
    top_k: int = 5


@router.post("/ask")
async def ask_endpoint(
    body: AskRequest,
    tenant_id: str = Depends(get_tenant_id),
    user_role: str = Depends(get_user_role),
):
    log.info(f"[ask] session={body.session_id} tenant={tenant_id} role={user_role}")

    history = get_history(body.session_id)
    history.append({"role": "user", "content": body.query})

    session = get_session(body.session_id)
    agent = RetrieverAgent(tenant_id=tenant_id, session=session)
    stream, citations = agent.run(history)

    def event_stream():
        answer = ""
        try:
            for chunk in stream:
                if isinstance(chunk, dict):
                    log.info(f"[ask] tool_call={chunk.get('name')} args={chunk.get('args')}")
                    yield f"data: {json.dumps(chunk)}\n\n"
                else:
                    answer += chunk
                    yield f"data: {json.dumps({'type': 'token', 'value': chunk})}\n\n"
        except Exception:
            err = traceback.format_exc()
            log.error(f"[ask] stream error:\n{err}")
            yield f"data: {json.dumps({'type': 'error', 'value': 'An error occurred. Check server logs.'})}\n\n"
        finally:
            try:
                append_messages(body.session_id, [
                    {"role": "user",      "content": body.query},
                    {"role": "assistant", "content": answer},
                ])
            except Exception:
                log.error("[ask] failed to save messages", exc_info=True)

            yield f"data: {json.dumps({'type': 'citations', 'value': citations})}\n\n"
            yield "data: [DONE]\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")
