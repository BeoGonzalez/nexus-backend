from __future__ import annotations
import uuid
from sqlalchemy import CheckConstraint, Enum, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from nexus_core.infrastructure.database import Base, TimestampMixin
from orders_service.domain.entities import OrderStatus


class OrderModel(TimestampMixin, Base):
    __tablename__ = "orders"
    __table_args__ = (
        CheckConstraint("total_amount_clp >= 0", name="ck_orders_non_negative_total"),
    )

    user_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    user_email: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    total_amount_clp: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[OrderStatus] = mapped_column(
        Enum(
            OrderStatus,
            name="order_status_enum",
            values_callable=lambda enum_cls: [e.value for e in enum_cls],
        ),
        default=OrderStatus.PENDING,
        nullable=False,
    )
    idempotency_key: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)

    items: Mapped[list["OrderItemModel"]] = relationship(
        back_populates="order", cascade="all, delete-orphan", lazy="selectin",
    )


class OrderItemModel(TimestampMixin, Base):
    __tablename__ = "order_items"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_order_items_positive_qty"),
        CheckConstraint("unit_price_clp > 0", name="ck_order_items_positive_price"),
    )

    order_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("orders.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    product_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    product_title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    unit_price_clp: Mapped[int] = mapped_column(Integer, nullable=False)

    order: Mapped[OrderModel] = relationship(back_populates="items")
