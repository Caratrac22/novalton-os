"""Persistent normalized model definition."""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, CheckConstraint, DateTime, Index, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from novalton_api.core.database import Base
from novalton_api.core.limits import MAX_CATALOG_OUTPUT_TOKENS
from novalton_api.core.models import TimestampMixin, UUIDPrimaryKeyMixin


class ModelDefinition(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Global provider/model metadata; permissions remain outside this table."""

    __tablename__ = "model_definitions"
    __table_args__ = (
        CheckConstraint(
            "char_length(provider_id) BETWEEN 1 AND 64",
            name="ck_model_definitions_provider_id_length",
        ),
        CheckConstraint(
            "char_length(provider_model_id) BETWEEN 1 AND 256",
            name="ck_model_definitions_provider_model_id_length",
        ),
        CheckConstraint(
            "char_length(display_name) BETWEEN 1 AND 200",
            name="ck_model_definitions_display_name_length",
        ),
        CheckConstraint(
            "status IN ('AVAILABLE', 'UNAVAILABLE', 'STALE', 'UNKNOWN')",
            name="ck_model_definitions_status_value",
        ),
        CheckConstraint(
            "context_window IS NULL OR context_window BETWEEN 1 AND 10000000",
            name="ck_model_definitions_context_window_value",
        ),
        CheckConstraint(
            "max_output_tokens IS NULL OR max_output_tokens BETWEEN 1 AND "
            f"{MAX_CATALOG_OUTPUT_TOKENS}",
            name="ck_model_definitions_max_output_tokens_value",
        ),
        CheckConstraint(
            "contract_enforcement_grade IN "
            "('UNSUPPORTED', 'BEST_EFFORT', 'PROVIDER_ENFORCED', 'STRICT_SCHEMA_GUARANTEED')",
            name="ck_model_definitions_contract_enforcement_grade",
        ),
        CheckConstraint(
            "char_length(enforcement_metadata_source) BETWEEN 1 AND 64",
            name="ck_model_definitions_enforcement_metadata_source_length",
        ),
        CheckConstraint(
            "input_price_per_million IS NULL OR input_price_per_million >= 0",
            name="ck_model_definitions_input_price_non_negative",
        ),
        CheckConstraint(
            "output_price_per_million IS NULL OR output_price_per_million >= 0",
            name="ck_model_definitions_output_price_non_negative",
        ),
        CheckConstraint(
            "((input_price_per_million IS NULL AND output_price_per_million IS NULL) "
            "AND currency IS NULL) OR ((input_price_per_million IS NOT NULL OR "
            "output_price_per_million IS NOT NULL) AND char_length(currency) = 3)",
            name="ck_model_definitions_pricing_currency",
        ),
        CheckConstraint(
            "family IS NULL OR char_length(family) BETWEEN 1 AND 128",
            name="ck_model_definitions_family_length",
        ),
        CheckConstraint(
            "revision IS NULL OR char_length(revision) BETWEEN 1 AND 128",
            name="ck_model_definitions_revision_length",
        ),
        UniqueConstraint(
            "provider_id",
            "provider_model_id",
            name="uq_model_definitions_provider_id_provider_model_id",
        ),
        Index(
            "ix_model_definitions_status_provider_model",
            "status",
            "provider_id",
            "provider_model_id",
        ),
    )

    provider_id: Mapped[str] = mapped_column(String(64), nullable=False)
    provider_model_id: Mapped[str] = mapped_column(String(256), nullable=False)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="UNKNOWN")
    context_window: Mapped[int | None] = mapped_column(nullable=True)
    max_output_tokens: Mapped[int | None] = mapped_column(nullable=True)
    reasoning: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    coding: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    tool_calling: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    structured_output: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    contract_enforcement_grade: Mapped[str] = mapped_column(
        String(32), nullable=False, default="UNSUPPORTED", server_default="UNSUPPORTED"
    )
    enforcement_metadata_source: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default="catalog_unknown",
        server_default="catalog_unknown",
    )
    vision: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    input_price_per_million: Mapped[Decimal | None] = mapped_column(Numeric(20, 10), nullable=True)
    output_price_per_million: Mapped[Decimal | None] = mapped_column(Numeric(20, 10), nullable=True)
    currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    free_allowlisted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    family: Mapped[str | None] = mapped_column(String(128), nullable=True)
    revision: Mapped[str | None] = mapped_column(String(128), nullable=True)
    last_verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
