import logging
from collections.abc import Callable

from fastapi import Depends, HTTPException, status

from nexus_core.infrastructure.logging import log_security_event
from nexus_security.dependencies import get_current_user
from nexus_security.jwt import TokenPayload


def require_role(required_role: str) -> Callable:
    """Dependency factory que restringe el acceso según el rol del usuario.

    Auditoría (A09): toda denegación (`authz.denied`) y todo uso de privilegios de administrador
    (`authz.admin_access`) se registran con el `sub` del token.
    """

    async def role_checker(user: TokenPayload = Depends(get_current_user)) -> TokenPayload:
        if user.role != required_role and user.role != "admin":
            log_security_event("authz.denied", user_sub=user.sub, user_role=user.role, required_role=required_role)
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Se requiere rol '{required_role}' para realizar esta acción.",
            )
        if user.role == "admin":
            log_security_event(
                "authz.admin_access", level=logging.INFO, user_sub=user.sub, required_role=required_role
            )
        return user

    return role_checker
