import json
import logging
import time
import traceback

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from ..agents.retriever import RetrieverAgent
from ..core.deps import get_tenant_id, get_user_role
from ..core.metrics import record_request, record_retrieval, record_tool_call
from ..core.session import append_messages, get_history, get_session

router = APIRouter()
log = logging.getLogger(__name__)

# gpt-4.1 pricing (per 1M tokens)
_COST_INPUT  = 2.00
_COST_OUTPUT = 8.00


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
    started = time.perf_counter()
    log.info(f"[ask] session={body.session_id} tenant={tenant_id} role={user_role}")

    history = get_history(body.session_id, agent="RetrieverAgent")
    history.append({"role": "user", "content": body.query})

    session = get_session(body.session_id)
    agent = RetrieverAgent(tenant_id=tenant_id, session=session, knowledge_only=False)
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
            err = traceback.format_exc()
            log.error(f"[ask] stream error:\n{err}")
            yield f"data: {json.dumps({'type': 'error', 'value': 'An error occurred. Check server logs.'})}\n\n"
        finally:
            latency = round(time.perf_counter() - started, 3)
            in_tok  = agent.usage["input_tokens"]
            out_tok = agent.usage["output_tokens"]
            cost    = round((in_tok * _COST_INPUT + out_tok * _COST_OUTPUT) / 1_000_000, 6)
            log.info(
                f"[ask] done session={body.session_id} latency={latency}s "
                f"tokens=({in_tok}in/{out_tok}out) cost=${cost}"
            )

            record_request(latency * 1000)
            for msg in agent.tool_messages:
                if msg.get("type") == "function_call":
                    name = msg.get("name", "")
                    record_tool_call(name)
                    if name == "search_knowledge":
                        output_msg = next(
                            (m for m in agent.tool_messages if m.get("type") == "function_call_output" and m.get("call_id") == msg.get("call_id")),
                            None,
                        )
                        if output_msg:
                            results = json.loads(output_msg.get("output", "[]"))
                            record_retrieval(hit=len(results) > 0)

            log.debug(f"[answer] session={body.session_id} text={answer[:400]!r}")

            if not error:
                try:
                    messages = (
                        [{"role": "user", "content": body.query}]
                        + agent.tool_messages
                        + [{"role": "assistant", "content": answer}]
                    )
                    append_messages(body.session_id, messages, agent="RetrieverAgent")
                except Exception:
                    log.error("[ask] failed to save messages", exc_info=True)

            yield "data: [DONE]\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")
