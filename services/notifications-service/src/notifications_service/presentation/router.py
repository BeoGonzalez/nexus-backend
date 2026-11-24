from datetime import datetime, timezone
import logging
from typing import Any
from fastapi import APIRouter, Depends, HTTPException, status
import html as _html
import uuid

from pydantic import BaseModel, ConfigDict, Field

from notifications_service.infrastructure.email_adapter import SmtpEmailAdapter
from nexus_security.dependencies import get_current_user
from nexus_security.jwt import TokenPayload
from nexus_security.permissions import require_role

logger = logging.getLogger("notifications.router")

router = APIRouter(prefix="/api/v1/notifications", tags=["Notifications Service"])


_REF = r"^[A-Za-z0-9._:-]{1,64}$"  # folio / transacción: sin CR/LF (inyección de cabeceras) ni HTML


class ReceiptItemDTO(BaseModel):
    model_config = ConfigDict(extra="ignore")

    title: str | None = Field(default=None, max_length=200)
    product_title: str | None = Field(default=None, max_length=200)
    quantity: int = Field(default=1, ge=1, le=100)
    unit_price_clp: int = Field(default=0, ge=0, le=100_000_000)
    subtotal_clp: int | None = Field(default=None, ge=0, le=1_000_000_000)


class LicenseKeyDTO(BaseModel):
    model_config = ConfigDict(extra="ignore")

    product_title: str | None = Field(default=None, max_length=200)
    key: str | None = Field(default=None, max_length=100)


class ReceiptBodyDTO(BaseModel):
    model_config = ConfigDict(extra="ignore")

    folio: str | None = Field(default=None, pattern=_REF)
    transaction_id: str | None = Field(default=None, pattern=_REF)
    customer_name: str | None = Field(default=None, max_length=200)
    total_clp: int | None = Field(default=None, ge=0, le=1_000_000_000)
    total_amount_clp: int | None = Field(default=None, ge=0, le=1_000_000_000)
    subtotal_neto_clp: int | None = Field(default=None, ge=0, le=1_000_000_000)
    iva_clp: int | None = Field(default=None, ge=0, le=1_000_000_000)
    items: list[ReceiptItemDTO] = Field(default_factory=list, max_length=50)
    license_keys: list[LicenseKeyDTO] = Field(default_factory=list, max_length=50)


class SendReceiptDTO(BaseModel):
    """Boleta: TODO campo del cliente es dato a escapar; la plantilla y el asunto los decide el servidor."""

    model_config = ConfigDict(extra="ignore")

    order_id: uuid.UUID
    customer_email: str = Field(max_length=320)
    customer_name: str | None = Field(default=None, max_length=200)
    receipt: ReceiptBodyDTO | None = None
    folio: str | None = Field(default=None, pattern=_REF)
    total_amount_clp: int | None = Field(default=None, ge=0, le=1_000_000_000)
    items: list[ReceiptItemDTO] | None = Field(default=None, max_length=50)
    license_keys: list[LicenseKeyDTO] | None = Field(default=None, max_length=50)
    transaction_id: str | None = Field(default=None, pattern=_REF)
    # Aceptados por compatibilidad con el BFF, pero IGNORADOS: un cliente que llame directo a la API no puede
    # convertir el correo oficial de la tienda en un mensaje de phishing con HTML o asunto propios.
    subject: str | None = Field(default=None, max_length=300)
    html_content: str | None = Field(default=None, max_length=100_000)


class GenericEmailDTO(BaseModel):
    recipient: str
    subject: str
    body_html: str


def _e(value: object) -> str:
    """Escape HTML de cualquier dato del cliente antes de interpolarlo (OWASP A05)."""
    return _html.escape(str(value), quote=True)


@router.get("/health")
async def health_check() -> dict[str, str]:
    return {"status": "healthy", "service": "notifications-service"}


@router.post("/send-receipt", status_code=status.HTTP_200_OK)
async def send_receipt(
    payload: SendReceiptDTO,
    current_user: TokenPayload = Depends(get_current_user),
) -> dict[str, Any]:
    """Emite y envía por correo electrónico la boleta electrónica fiscal y claves digitales.

    Solo al correo del propio usuario autenticado: si no, el endpoint sería un relay de correo.
    """
    requested = (payload.customer_email or "").strip().lower()
    if not requested:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Se requiere un correo de destinatario válido.",
        )
    token_email = (current_user.email or "").strip().lower()
    if not token_email:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="El token no incluye un correo.",
        )
    if not current_user.email_verified:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Verifica tu correo antes de recibir la boleta.",
        )
    if requested != token_email:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Solo puedes enviarte la boleta a tu propio correo.",
        )
    recipient = token_email

    receipt = payload.receipt.model_dump() if payload.receipt else {}
    customer_name = _e(payload.customer_name or receipt.get("customer_name") or "Gamer")
    order_id = str(payload.order_id)
    folio = payload.folio or receipt.get("folio") or f"BOL-2026-NEXUS-{str(order_id)[:8]}"
    total_clp = (
        payload.total_amount_clp
        or receipt.get("total_clp")
        or receipt.get("total_amount_clp")
        or 0
    )
    subtotal_neto = receipt.get("subtotal_neto_clp") or int(total_clp / 1.19)
    iva_clp = receipt.get("iva_clp") or (total_clp - subtotal_neto)
    items = [i.model_dump() for i in payload.items] if payload.items else receipt.get("items") or []
    keys = [k.model_dump() for k in payload.license_keys] if payload.license_keys else receipt.get("license_keys") or []
    tx_id = (
        payload.transaction_id
        or receipt.get("transaction_id")
        or f"SIM-TXN-{str(order_id)[:8].upper()}"
    )

    items_html_rows = ""
    for item in items:
        title = _e(item.get("title") or item.get("product_title") or "Videojuego Digital")
        qty = int(item.get("quantity") or 1)
        unit = int(item.get("unit_price_clp") or 0)
        sub = int(item.get("subtotal_clp") or unit * qty)
        items_html_rows += f"""
        <tr style="border-bottom: 1px solid #1e293b;">
          <td style="padding: 10px 8px; font-weight: 600; color: #f1f5f9;">{title}</td>
          <td style="padding: 10px 8px; text-align: center; color: #94a3b8;">{qty}</td>
          <td style="padding: 10px 8px; text-align: right; color: #94a3b8;">${unit:,.0f} CLP</td>
          <td style="padding: 10px 8px; text-align: right; font-weight: 700; color: #48c8d8;">${sub:,.0f} CLP</td>
        </tr>
        """

    keys_html_rows = ""
    for key_info in keys:
        game_title = _e(key_info.get("product_title") or "Licencia Digital")
        k_code = _e(key_info.get("key") or "NEXUS-KEY-PENDING")
        keys_html_rows += f"""
        <div style="background-color: #0b1522; border: 1px dashed #48c8d8; border-radius: 8px; padding: 12px; margin-bottom: 8px;">
          <div style="font-size: 11px; color: #64748b; text-transform: uppercase; font-weight: bold; letter-spacing: 0.05em;">{game_title}</div>
          <div style="font-family: monospace; font-size: 16px; font-weight: 800; color: #38bdf8; letter-spacing: 0.1em; margin-top: 4px;">{k_code}</div>
        </div>
        """

    subject = f"🎮 Boleta Electrónica #{folio} — ¡Gracias por comprar en Nexus Digital Store!"

    html_content = f"""
    <!DOCTYPE html>
    <html>
    <body style="margin: 0; padding: 24px; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background-color: #050b14; color: #e2e8f0;">
      <div style="max-width: 600px; margin: 0 auto; background-color: #0e1726; border-radius: 16px; border: 1px solid #1e293b; overflow: hidden; box-shadow: 0 10px 30px rgba(0,0,0,0.5);">
        <div style="background: linear-gradient(135deg, #062029 0%, #0d3846 100%); padding: 28px 24px; border-bottom: 2px solid #48c8d8;">
          <div style="font-size: 22px; font-weight: 900; color: #ffffff; letter-spacing: -0.02em;">NEXUS DIGITAL STORE</div>
          <div style="font-size: 12px; color: #48c8d8; font-weight: 700; margin-top: 2px;">BOLETA ELECTRÓNICA DE VENTA Y LICENCIAS DIGITALES</div>
          <div style="font-size: 11px; color: #94a3b8; margin-top: 6px;">R.U.T.: 76.892.140-K | Folio Electrónico N° {folio}</div>
        </div>

        <div style="padding: 24px;">
          <h2 style="color: #38bdf8; font-size: 20px; margin: 0 0 12px 0;">¡Gracias por comprar en Nexus Digital Store!</h2>
          <p style="font-size: 15px; margin: 0 0 16px 0; color: #cbd5e1;">
            ¡Hola <strong>{customer_name}</strong>! Tu pago ha sido acreditado exitosamente. A continuación encuentras tu comprobante fiscal y tus claves digitales.
          </p>

          <div style="background-color: #070d17; border: 1px solid #1e293b; border-radius: 10px; padding: 14px 16px; margin-bottom: 20px; font-size: 13px;">
            <div style="display: flex; justify-content: space-between; margin-bottom: 6px;">
              <span style="color: #64748b;">N° Orden:</span>
              <span style="font-family: monospace; color: #e2e8f0; font-weight: 600;">{order_id}</span>
            </div>
            <div style="display: flex; justify-content: space-between; margin-bottom: 6px;">
              <span style="color: #64748b;">Fecha de emisión:</span>
              <span style="color: #e2e8f0;">{datetime.now(timezone.utc).strftime('%d/%m/%Y %H:%M:%S')} UTC</span>
            </div>
            <div style="display: flex; justify-content: space-between; margin-bottom: 6px;">
              <span style="color: #64748b;">Método de Pago:</span>
              <span style="color: #38bdf8; font-weight: 600;">Tarjeta Sandbox</span>
            </div>
            <div style="display: flex; justify-content: space-between;">
              <span style="color: #64748b;">ID Transacción Simulada:</span>
              <span style="font-family: monospace; color: #a5b4fc;">{tx_id}</span>
            </div>
          </div>

          <h3 style="font-size: 14px; font-weight: 800; text-transform: uppercase; letter-spacing: 0.05em; color: #48c8d8; margin: 20px 0 10px 0;">
            Detalle de Productos
          </h3>
          <table style="width: 100%; border-collapse: collapse; font-size: 13px; margin-bottom: 20px;">
            <thead>
              <tr style="border-bottom: 2px solid #334155; color: #64748b; font-size: 11px; text-transform: uppercase;">
                <th style="text-align: left; padding: 6px 8px;">Juego / Software</th>
                <th style="text-align: center; padding: 6px 8px;">Cant.</th>
                <th style="text-align: right; padding: 6px 8px;">Unitario</th>
                <th style="text-align: right; padding: 6px 8px;">Subtotal</th>
              </tr>
            </thead>
            <tbody>
              {items_html_rows}
            </tbody>
          </table>

          <div style="border-top: 1px solid #1e293b; padding-top: 12px; margin-bottom: 24px; font-size: 13px;">
            <div style="display: flex; justify-content: space-between; margin-bottom: 4px; color: #94a3b8;">
              <span>Subtotal Neto:</span>
              <span>${subtotal_neto:,.0f} CLP</span>
            </div>
            <div style="display: flex; justify-content: space-between; margin-bottom: 6px; color: #94a3b8;">
              <span>IVA (19%):</span>
              <span>${iva_clp:,.0f} CLP</span>
            </div>
            <div style="display: flex; justify-content: space-between; font-size: 18px; font-weight: 900; color: #ffffff; border-top: 1px dashed #334155; padding-top: 8px;">
              <span>TOTAL PAGADO:</span>
              <span style="color: #48c8d8;">${total_clp:,.0f} CLP</span>
            </div>
          </div>

          {f'''<h3 style="font-size: 14px; font-weight: 800; text-transform: uppercase; letter-spacing: 0.05em; color: #38bdf8; margin: 24px 0 12px 0;">
            🔑 Claves de Activación Digital
          </h3>
          <p style="font-size: 12px; color: #94a3b8; margin: 0 0 12px 0;">
            Canjea estas licencias directamente en Steam, PlayStation Network, Xbox o Epic Games:
          </p>
          {keys_html_rows}''' if keys_html_rows else ''}

          <div style="margin-top: 32px; border-top: 1px solid #1e293b; padding-top: 16px; font-size: 11px; color: #64748b; line-height: 1.5;">
            <p style="margin: 0;"><strong>Emisor:</strong> NEXUS DIGITAL STORE SpA | Giro: Venta de Software y Contenido Digital</p>
            <p style="margin: 2px 0;">Casa Matriz: Av. Providencia 1208, Of. 601, Santiago, Chile</p>
            <p style="margin: 6px 0 0 0; color: #48c8d8;">Documento tributario electrónico emitido bajo normativa SII Chile.</p>
          </div>
        </div>
      </div>
    </body>
    </html>
    """

    adapter = SmtpEmailAdapter()
    sent = await adapter.send_email(recipient, subject, html_content)

    if not sent:
        logger.error("Failed to send receipt email via SMTP to %s", recipient)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"No se pudo despachar el correo a {recipient} a través del servidor SMTP.",
        )

    logger.info("Receipt email successfully sent to %s for order %s", recipient, order_id)
    return {
        "success": True,
        "status": "sent",
        "message": f"Boleta electrónica y claves enviadas exitosamente a {recipient}",
        "order_id": order_id,
        "recipient_email": recipient,
        "folio": folio,
        "service": "notifications-service",
        "port": 8005,
        "sent_at": datetime.now(timezone.utc).isoformat(),
    }


@router.post("/email", status_code=status.HTTP_200_OK)
async def send_generic_email(
    payload: GenericEmailDTO,
    _admin: TokenPayload = Depends(require_role("admin")),
) -> dict[str, Any]:
    """Envía un correo genérico vía SMTP a través del microservicio de notificaciones."""
    recipient = payload.recipient.strip()
    if not recipient:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Se requiere un correo de destinatario válido.",
        )

    adapter = SmtpEmailAdapter()
    sent = await adapter.send_email(recipient, payload.subject, payload.body_html)

    if not sent:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"No se pudo despachar el correo a {recipient}.",
        )

    return {
        "success": True,
        "status": "sent",
        "recipient": recipient,
        "service": "notifications-service",
        "port": 8005,
    }
