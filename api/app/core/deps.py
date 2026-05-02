from fastapi import Header, HTTPException


async def get_tenant_id(x_tenant_id: str = Header(...)) -> str:
    if not x_tenant_id:
        raise HTTPException(status_code=400, detail="X-Tenant-Id header required")
    return x_tenant_id


async def get_user_role(x_user_role: str = Header(default="patient")) -> str:
    if x_user_role not in ("staff", "patient"):
        raise HTTPException(status_code=400, detail="X-User-Role must be 'staff' or 'patient'")
    return x_user_role
