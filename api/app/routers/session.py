import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ..core.deps import get_tenant_id, get_user_role
from ..core.session import create_session

router = APIRouter()


class SessionRequest(BaseModel):
    tenant_name:  str | None = None
    patient_id:   str | None = None
    patient_name: str | None = None


class SessionResponse(BaseModel):
    session_id: str


@router.post("/session", response_model=SessionResponse)
async def create_session_endpoint(
    body: SessionRequest,
    tenant_id: str = Depends(get_tenant_id),
    role: str = Depends(get_user_role),
):
    session_id = str(uuid.uuid4())
    create_session(
        session_id,
        tenant_id,
        body.tenant_name,
        role,
        body.patient_id,
        body.patient_name,
    )
    return SessionResponse(session_id=session_id)
