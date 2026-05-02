from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ..agents.retriever import RetrieverAgent
from ..core.deps import get_tenant_id, get_user_role

router = APIRouter()


class AskRequest(BaseModel):
    query: str
    top_k: int = 5


class AskResponse(BaseModel):
    answer: str
    citations: list[str]


@router.post("/ask", response_model=AskResponse)
async def ask_endpoint(
    body: AskRequest,
    tenant_id: str = Depends(get_tenant_id),
    user_role: str = Depends(get_user_role),
):
    agent = RetrieverAgent(tenant_id=tenant_id)
    stream, citations = agent.run([{"role": "user", "content": body.query}])
    answer = "".join(stream)
    return AskResponse(answer=answer, citations=citations)
