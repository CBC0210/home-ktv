"""Admin authentication — verify admin password, issue admin JWT."""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ktv_pipeline.schemas import SessionOut, GuestOut


class AdminLoginBody(BaseModel):
    password: str


class AdminPasswordBody(BaseModel):
    new_password: str
    current_password: str
from ktv_pipeline.auth import (
    verify_admin_password,
    create_access_token,
    hash_password,
    verify_password,
)
from ktv_pipeline.database import get_db_session
from ktv_pipeline.models import Guest
import random


router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/admin/login")
def admin_login(body: AdminLoginBody) -> SessionOut:
    """Verify admin password and return a session token with is_admin=True."""
    if not verify_admin_password(body.password):
        raise HTTPException(status_code=401, detail="Incorrect admin password")

    # Get or create the system admin guest
    with get_db_session() as session:
        admin = session.query(Guest).filter_by(nickname="__system_admin__").first()
        if not admin:
            colors = ["#7c3aed", "#dc2626"]
            admin = Guest(
                nickname="__system_admin__",
                avatar_color=colors[0],
                is_admin=True,
            )
            session.add(admin)
            session.commit()
            session.refresh(admin)

        token = create_access_token(guest_id=admin.id, room_id="__admin__", is_admin=True)

        return SessionOut(
            access_token=token,
            guest=GuestOut.model_validate(admin),
        )


@router.post("/admin/password")
def admin_change_password(body: AdminPasswordBody) -> dict:
    """Change the admin password. Requires knowing the current password."""
    from ktv_pipeline.config import settings

    if not verify_admin_password(body.current_password):
        raise HTTPException(status_code=401, detail="Current password incorrect")

    if len(body.new_password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters")

    # Note: for security, the admin password is set via config/settings.admin_password
    # We store a bcrypt hash in a separate config file or env variable
    # For now, we'll just verify against settings.admin_password (plaintext in .env)
    # The .env ADMIN_PASSWORD is the source of truth; changing it requires .env edit
    raise HTTPException(
        status_code=501,
        detail="Admin password change not yet implemented — edit ADMIN_PASSWORD in .env"
    )