from __future__ import annotations
import uuid
from sqlalchemy import CheckConstraint, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from nexus_core.infrastructure.database import Base, TimestampMixin


class GenreModel(TimestampMixin, Base):
    __tablename__ = "genres"

    name: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    products: Mapped[list["ProductModel"]] = relationship(
        secondary="product_genres", back_populates="genres",
    )


class ProductGenreModel(Base):
    __tablename__ = "product_genres"

    product_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"), primary_key=True,
    )
    genre_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("genres.id", ondelete="CASCADE"), primary_key=True,
    )


class PlatformModel(TimestampMixin, Base):
    __tablename__ = "platforms"

    name: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    products: Mapped[list["ProductModel"]] = relationship(back_populates="platform")


class ProductModel(TimestampMixin, Base):
    __tablename__ = "products"
    __table_args__ = (
        CheckConstraint("price_clp > 0", name="ck_products_positive_price"),
        CheckConstraint("stock >= 0", name="ck_products_non_negative_stock"),
    )

    title: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    price_clp: Mapped[int] = mapped_column(Integer, nullable=False)
    stock: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    image_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    platform_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("platforms.id", ondelete="SET NULL"), nullable=True,
    )

    platform: Mapped[PlatformModel | None] = relationship(back_populates="products", lazy="selectin")
    genres: Mapped[list[GenreModel]] = relationship(
        secondary="product_genres", back_populates="products", lazy="selectin",
    )

