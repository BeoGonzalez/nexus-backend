import html
import logging
from notifications_service.domain.ports import EmailSenderPort

logger = logging.getLogger("notifications.handlers")


def _text(value: object, max_len: int = 200) -> str:
    """Todo dato del evento se escapa antes de interpolarse en HTML (OWASP A05: inyección HTML en correos)."""
    return html.escape(str(value)[:max_len], quote=False)  # solo nodos de texto, nunca atributos


def _int(value: object) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


class NotificationEventHandler:
    def __init__(self, email_sender: EmailSenderPort) -> None:
        self._sender = email_sender

    async def handle_order_created(self, event_data: dict) -> bool:
        user_id = event_data.get("user_id", "")
        order_id = _text(event_data.get("order_id", ""))
        total = _int(event_data.get("total_amount_clp", 0))
        recipient = event_data.get("user_email") or f"{user_id}@nexus-store.cl"

        subject = f"¡Tu orden #{str(order_id)[:8]} ha sido creada en Nexus Store!"
        body = f"""
        <h2>¡Gracias por tu pedido en Nexus Digital Store! 🎮</h2>
        <p>Tu orden <strong>#{order_id}</strong> está registrada.</p>
        <p>Total: <strong>${total:,} CLP</strong></p>
        <p>Estado: Pendiente de confirmación de pago.</p>
        """
        logger.info("Sending order created notification to %s for order %s", recipient, order_id)
        return await self._sender.send_email(recipient, subject, body)

    async def handle_payment_succeeded(self, event_data: dict) -> bool:
        user_id = event_data.get("user_id", "")
        order_id = _text(event_data.get("order_id", ""))
        amount = _int(event_data.get("amount_paid_clp", 0))
        payment_id = _text(event_data.get("payment_id", "N/A"))
        recipient = event_data.get("user_email") or f"{user_id}@nexus-store.cl"
        items = event_data.get("items", [])

        # Armar filas de la tabla de la boleta
        items_rows = ""
        if items:
            for item in items:
                title = _text(item.get("product_title") or "Videojuego Digital")
                qty = _int(item.get("quantity", 1))
                unit_price = _int(item.get("unit_price_clp", 0))
                subtotal = qty * unit_price
                items_rows += f"""
                <tr style="border-bottom: 1px solid #2d325a;">
                    <td style="padding: 12px; color: #f1f5f9; font-weight: 500;">🎮 {title}</td>
                    <td style="padding: 12px; text-align: center; color: #94a3b8;">{qty}</td>
                    <td style="padding: 12px; text-align: right; color: #cbd5e1;">${unit_price:,} CLP</td>
                    <td style="padding: 12px; text-align: right; color: #10b981; font-weight: bold;">${subtotal:,} CLP</td>
                </tr>
                """
        else:
            items_rows = f"""
            <tr style="border-bottom: 1px solid #2d325a;">
                <td style="padding: 12px; color: #f1f5f9; font-weight: 500;">🎮 Orden de Compra Digital Nexus</td>
                <td style="padding: 12px; text-align: center; color: #94a3b8;">1</td>
                <td style="padding: 12px; text-align: right; color: #cbd5e1;">${amount:,} CLP</td>
                <td style="padding: 12px; text-align: right; color: #10b981; font-weight: bold;">${amount:,} CLP</td>
            </tr>
            """

        subject = f"¡Boleta de Compra #{str(order_id)[:8]} - Gracias por comprar en Nexus Digital Store! 🎮"
        body = f"""<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <title>Boleta Electrónica - Nexus Digital Store</title>
</head>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background-color: #0b0f19; color: #e2e8f0; margin: 0; padding: 24px;">
  <div style="max-width: 600px; margin: 0 auto; background: #131b2e; border: 1px solid #242f4c; border-radius: 12px; overflow: hidden; box-shadow: 0 10px 25px rgba(0,0,0,0.5);">
    
    <!-- Encabezado de Marca -->
    <div style="background: linear-gradient(135deg, #4f46e5 0%, #7c3aed 100%); padding: 28px; text-align: center;">
      <h1 style="margin: 0; color: #ffffff; font-size: 26px; letter-spacing: 1px;">NEXUS DIGITAL STORE 🎮</h1>
      <p style="margin: 6px 0 0; color: #e0e7ff; font-size: 14px;">Tu portal de videojuegos digitales de nueva generación</p>
    </div>

    <div style="padding: 30px;">
      <!-- Mensaje Central -->
      <div style="text-align: center; margin-bottom: 25px;">
        <h2 style="color: #38bdf8; margin: 0 0 8px; font-size: 22px;">¡Gracias por comprar en Nexus Digital Store!</h2>
        <p style="margin: 0; color: #94a3b8; font-size: 15px;">Tu pago ha sido confirmado exitosamente y tus licencias ya están disponibles.</p>
      </div>

      <!-- Resumen de Boleta -->
      <div style="background: #1e293b; border-radius: 8px; padding: 18px; margin-bottom: 24px; font-size: 13px;">
        <table style="width: 100%; border-collapse: collapse;">
          <tr>
            <td style="padding: 4px 0; color: #94a3b8;"><strong>N° de Boleta / Orden:</strong></td>
            <td style="padding: 4px 0; text-align: right; color: #f8fafc;"><code style="background: #0f172a; padding: 2px 6px; border-radius: 4px;">#{order_id}</code></td>
          </tr>
          <tr>
            <td style="padding: 4px 0; color: #94a3b8;"><strong>ID Transacción Pago:</strong></td>
            <td style="padding: 4px 0; text-align: right; color: #f8fafc;"><code style="background: #0f172a; padding: 2px 6px; border-radius: 4px;">{payment_id}</code></td>
          </tr>
          <tr>
            <td style="padding: 4px 0; color: #94a3b8;"><strong>Cliente Comprador:</strong></td>
            <td style="padding: 4px 0; text-align: right; color: #38bdf8;">{html.escape(recipient)}</td>
          </tr>
        </table>
      </div>

      <!-- Tabla de Productos -->
      <table style="width: 100%; border-collapse: collapse; margin-bottom: 20px; font-size: 14px;">
        <thead>
          <tr style="background: #1e293b; color: #94a3b8; text-align: left; font-size: 12px; text-transform: uppercase;">
            <th style="padding: 10px 12px;">Videojuego</th>
            <th style="padding: 10px 12px; text-align: center;">Cant.</th>
            <th style="padding: 10px 12px; text-align: right;">Unitario</th>
            <th style="padding: 10px 12px; text-align: right;">Total</th>
          </tr>
        </thead>
        <tbody>
          {items_rows}
        </tbody>
      </table>

      <!-- Total -->
      <div style="background: #1e293b; border-radius: 8px; padding: 16px; text-align: right; margin-bottom: 24px;">
        <span style="font-size: 15px; color: #94a3b8; margin-right: 12px;">TOTAL PAGADO:</span>
        <span style="font-size: 24px; font-weight: bold; color: #10b981;">${amount:,} CLP</span>
      </div>

      <!-- Activación y Licencias -->
      <div style="background: rgba(56, 189, 248, 0.1); border-left: 4px solid #38bdf8; padding: 14px 18px; border-radius: 4px; margin-bottom: 25px;">
        <p style="margin: 0; color: #e2e8f0; font-size: 14px;">
          🚀 <strong>Descarga Inmediata:</strong> Tus códigos y licencias digitales han sido asociados a tu cuenta. Puedes iniciar sesión y activarlos de inmediato en tu plataforma elegida (PC, PS5, Xbox Series o Switch 2).
        </p>
      </div>

      <!-- Footer -->
      <div style="border-top: 1px solid #242f4c; padding-top: 18px; text-align: center; color: #64748b; font-size: 12px;">
        <p style="margin: 4px 0;">Este correo sirve como comprobante de pago oficial y boleta electrónica digital.</p>
        <p style="margin: 4px 0;">© 2026 Nexus Digital Store Inc. Todos los derechos reservados.</p>
      </div>

    </div>
  </div>
</body>
</html>
"""
        logger.info("Sending payment succeeded confirmation receipt to %s for order %s", recipient, order_id)
        return await self._sender.send_email(recipient, subject, body)

    async def handle_user_registered(self, event_data: dict) -> bool:
        email = event_data.get("email", "")
        name = _text(event_data.get("full_name") or "Gamer")
        subject = "¡Bienvenido a Nexus Digital Store! 🎮"
        body = f"""
        <h2>¡Hola {name}!</h2>
        <p>Bienvenido a la comunidad gamer de Nexus Digital Store.</p>
        <p>Ya puedes explorar nuestro catálogo y acceder a tus compras digitales.</p>
        """
        logger.info("Sending welcome email to %s", email)
        return await self._sender.send_email(email, subject, body)
