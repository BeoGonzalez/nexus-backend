"""Identificador de petición (`X-Request-ID`) compartido por middleware, errores y logs."""

import re
import uuid

from starlette.requests import HTTPConnection

REQUEST_ID_HEADER = "X-Request-ID"
_VALID = re.compile(r"^[A-Za-z0-9._-]{8,64}$")


def get_request_id(conn: HTTPConnection) -> str:
    """Devuelve el request id de la petición: el ya asignado, el del cliente si es seguro, o uno nuevo."""
    existing = getattr(conn.state, "request_id", None)
    if existing:
        return existing
    incoming = conn.headers.get(REQUEST_ID_HEADER, "")
    request_id = incoming if _VALID.match(incoming) else uuid.uuid4().hex
    conn.state.request_id = request_id
    return request_id
