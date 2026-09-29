"""
Database models and session management.
All models use SQLAlchemy 2.x mapped_column style.
"""
import enum
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    BigInteger, Boolean, DateTime, Enum, Float, ForeignKey, Integer,
    String, Text, func, inspect, text,
)
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

import os

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./tender_mvp.db")
# Ensure aiosqlite driver for async
if DATABASE_URL.startswith("sqlite:///") and "aiosqlite" not in DATABASE_URL:
    DATABASE_URL = DATABASE_URL.replace("sqlite:///", "sqlite+aiosqlite:///")

engine = create_async_engine(DATABASE_URL, echo=False, future=True)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def get_db():
    async with AsyncSessionLocal() as session:
        yield session


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_ensure_legacy_columns)
    # The legacy NOT NULL rebuild must run with SQLite foreign-key enforcement
    # disabled outside the create_all transaction, then re-enable it immediately.
    async with engine.connect() as conn:
        await conn.run_sync(_ensure_nullable_master_prices)


def _ensure_legacy_columns(connection) -> None:
    """Add nullable governance columns to existing local SQLite databases."""
    if connection.dialect.name != "sqlite":
        return
    additions = {
        "master_items": {
            "created_by": "VARCHAR(128)", "created_at": "DATETIME", "last_updated_by": "VARCHAR(128)",
            "last_updated_at": "DATETIME", "price_source_reference": "TEXT", "price_effective_date": "VARCHAR(32)",
            "price_expiry_date": "VARCHAR(32)", "approval_status": "VARCHAR(32)", "approved_by": "VARCHAR(128)",
            "zero_price_authorized": "BOOLEAN DEFAULT 0",
        },
        "unit_rules": {
            "created_by": "VARCHAR(128)", "created_at": "DATETIME", "last_updated_by": "VARCHAR(128)",
            "last_updated_at": "DATETIME", "source_reference": "TEXT", "effective_date": "VARCHAR(32)",
            "expiry_date": "VARCHAR(32)", "approval_status": "VARCHAR(32)", "approved_by": "VARCHAR(128)",
        },
        "coefficients": {
            "created_by": "VARCHAR(128)", "created_at": "DATETIME", "last_updated_by": "VARCHAR(128)",
            "last_updated_at": "DATETIME", "source_reference": "TEXT", "effective_date": "VARCHAR(32)",
            "expiry_date": "VARCHAR(32)", "approval_status": "VARCHAR(32)", "approved_by": "VARCHAR(128)",
        },
        "mapping_results": {
            "pricing_availability": "VARCHAR(32)", "price_effective_date": "VARCHAR(32)",
            "price_expiry_date": "VARCHAR(32)", "price_source_reference": "TEXT",
            "price_last_updated_by": "VARCHAR(128)", "price_last_updated_at": "DATETIME",
            "mapping_last_updated_by": "VARCHAR(128)", "mapping_last_updated_at": "DATETIME",
            "mapped_by": "VARCHAR(128)",
            "price_review_required": "BOOLEAN DEFAULT 0",
        },
        "boq_rows": {
            "source_origin": "VARCHAR(64) DEFAULT 'azure_document_intelligence'",
            "source_provenance": "TEXT",
            "azure_polygon_available": "BOOLEAN DEFAULT 1",
        },
    }
    inspector = inspect(connection)
    available_tables = set(inspector.get_table_names())
    for table_name, columns in additions.items():
        if table_name not in available_tables:
            continue
        existing = {column["name"] for column in inspector.get_columns(table_name)}
        for column_name, ddl in columns.items():
            if column_name not in existing:
                connection.execute(text(f'ALTER TABLE "{table_name}" ADD COLUMN "{column_name}" {ddl}'))


def _ensure_nullable_master_prices(connection) -> None:
    """Rebuild only the legacy SQLite table whose price column was NOT NULL.

    SQLite cannot drop a NOT NULL constraint in place. The copy is performed in
    one transaction and preserves primary keys, all existing rows, mapping FKs,
    and audit metadata. Fresh databases already have a nullable column and skip
    this migration.
    """
    if connection.dialect.name != "sqlite":
        return
    columns = {column["name"]: column for column in inspect(connection).get_columns("master_items")}
    unit_price = columns.get("unit_price")
    if not unit_price or unit_price.get("nullable", True):
        return
    connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
    connection.execute(text("""
        CREATE TABLE master_items_nullable_upgrade (
            id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
            tenant_id VARCHAR(64) NOT NULL,
            version VARCHAR(16) NOT NULL,
            item_code VARCHAR(64) NOT NULL,
            description_vi TEXT NOT NULL,
            unit VARCHAR(64) NOT NULL,
            unit_price FLOAT NULL,
            formula_ref VARCHAR(128) NULL,
            source_sheet VARCHAR(128) NULL,
            tags_json TEXT NULL,
            created_by VARCHAR(128) NULL,
            created_at DATETIME NULL,
            last_updated_by VARCHAR(128) NULL,
            last_updated_at DATETIME NULL,
            price_source_reference TEXT NULL,
            price_effective_date VARCHAR(32) NULL,
            price_expiry_date VARCHAR(32) NULL,
            approval_status VARCHAR(32) NULL,
            approved_by VARCHAR(128) NULL,
            zero_price_authorized BOOLEAN NOT NULL DEFAULT 0
        )
    """))
    ordered_columns = [
        "id", "tenant_id", "version", "item_code", "description_vi", "unit", "unit_price",
        "formula_ref", "source_sheet", "tags_json", "created_by", "created_at", "last_updated_by",
        "last_updated_at", "price_source_reference", "price_effective_date", "price_expiry_date",
        "approval_status", "approved_by", "zero_price_authorized",
    ]
    names = ", ".join(f'"{name}"' for name in ordered_columns)
    connection.execute(text(f"INSERT INTO master_items_nullable_upgrade ({names}) SELECT {names} FROM master_items"))
    before = connection.execute(text("SELECT COUNT(*) FROM master_items")).scalar_one()
    copied = connection.execute(text("SELECT COUNT(*) FROM master_items_nullable_upgrade")).scalar_one()
    if before != copied:
        raise RuntimeError(f"Master-data migration row-count mismatch: {before} != {copied}")
    connection.execute(text("DROP TABLE master_items"))
    connection.execute(text("ALTER TABLE master_items_nullable_upgrade RENAME TO master_items"))
    connection.execute(text("CREATE INDEX IF NOT EXISTS ix_master_items_tenant_id ON master_items (tenant_id)"))
    connection.commit()
    connection.exec_driver_sql("PRAGMA foreign_keys=ON")


class Base(DeclarativeBase):
    pass


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class JobStatus(str, enum.Enum):
    uploaded = "uploaded"
    parsing = "parsing"
    mapping = "mapping"
    pricing = "pricing"
    needs_review = "needs_review"
    ready = "ready"
    exported = "exported"
    failed = "failed"


class RowType(str, enum.Enum):
    heading = "heading"
    metadata = "metadata"
    line_item = "line_item"


class MappingStatus(str, enum.Enum):
    mapped_and_priced = "mapped_and_priced"
    mapped_price_unavailable = "mapped_price_unavailable"
    mapping_ambiguous = "mapping_ambiguous"
    mapping_unresolved = "mapping_unresolved"
    invalid_quantity_or_unit = "invalid_quantity_or_unit"
    non_billable_heading = "non_billable_heading"
    non_billable_metadata = "non_billable_metadata"


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    filename: Mapped[str] = mapped_column(String(256), nullable=False)
    status: Mapped[JobStatus] = mapped_column(
        Enum(JobStatus), nullable=False, default=JobStatus.uploaded
    )
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    parsed_document: Mapped[Optional["ParsedDocument"]] = relationship(
        back_populates="job", uselist=False, cascade="all, delete-orphan"
    )
    boq_rows: Mapped[list["BOQRow"]] = relationship(
        back_populates="job", cascade="all, delete-orphan"
    )
    overrides: Mapped[list["Override"]] = relationship(
        back_populates="job", cascade="all, delete-orphan"
    )
    exports: Mapped[list["ExportRecord"]] = relationship(
        back_populates="job", cascade="all, delete-orphan"
    )
    stage_events: Mapped[list["JobStageEvent"]] = relationship(
        back_populates="job", cascade="all, delete-orphan", order_by="JobStageEvent.id"
    )


class JobStageEvent(Base):
    """Append-only processing-state transition evidence for polling and UAT."""
    __tablename__ = "job_stage_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id"), nullable=False, index=True)
    stage: Mapped[str] = mapped_column(String(32), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    job: Mapped["Job"] = relationship(back_populates="stage_events")


class ParsedDocument(Base):
    """Raw Azure Document Intelligence output preserved verbatim."""
    __tablename__ = "parsed_documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id"), nullable=False, unique=True)
    raw_json: Mapped[str] = mapped_column(Text, nullable=False)  # full API response
    page_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    model_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    api_version: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    job: Mapped["Job"] = relationship(back_populates="parsed_document")


class BOQRow(Base):
    """Reconstructed BOQ line item / heading / metadata from the parsed document."""
    __tablename__ = "boq_rows"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id"), nullable=False, index=True)
    row_id: Mapped[str] = mapped_column(String(128), nullable=False)  # e.g. "IV.1-3"
    row_number: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    section_path: Mapped[str] = mapped_column(Text, nullable=False)
    description_vi: Mapped[str] = mapped_column(Text, nullable=False)
    unit_raw: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    quantity_raw: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)  # original string
    quantity: Mapped[Optional[float]] = mapped_column(Float, nullable=True)  # parsed float
    page: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    region: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    row_type: Mapped[RowType] = mapped_column(Enum(RowType), nullable=False)
    doc_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    source_origin: Mapped[str] = mapped_column(String(64), nullable=False, default="azure_document_intelligence")
    source_provenance: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    azure_polygon_available: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    job: Mapped["Job"] = relationship(back_populates="boq_rows")
    mapping_result: Mapped[Optional["MappingResult"]] = relationship(
        back_populates="boq_row", uselist=False, cascade="all, delete-orphan"
    )


class MasterItem(Base):
    """Versioned master pricing record seeded from the reference XLS."""
    __tablename__ = "master_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    version: Mapped[str] = mapped_column(String(16), nullable=False, default="v1")
    item_code: Mapped[str] = mapped_column(String(64), nullable=False)
    description_vi: Mapped[str] = mapped_column(Text, nullable=False)
    unit: Mapped[str] = mapped_column(String(64), nullable=False)
    unit_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)  # NULL means unavailable
    formula_ref: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    source_sheet: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    tags_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON dict
    created_by: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_updated_by: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    last_updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    price_source_reference: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    price_effective_date: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    price_expiry_date: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    approval_status: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    approved_by: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    zero_price_authorized: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class UnitRule(Base):
    """Approved unit conversion rules — never convert without an explicit entry."""
    __tablename__ = "unit_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    version: Mapped[str] = mapped_column(String(16), nullable=False, default="v1")
    from_unit: Mapped[str] = mapped_column(String(64), nullable=False)
    to_unit: Mapped[str] = mapped_column(String(64), nullable=False)
    factor: Mapped[float] = mapped_column(Float, nullable=False)  # to_unit = from_unit * factor
    note: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    created_by: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_updated_by: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    last_updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    source_reference: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    effective_date: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    expiry_date: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    approval_status: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    approved_by: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)


class Coefficient(Base):
    """Coefficients from Hệ số sheet."""
    __tablename__ = "coefficients"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    version: Mapped[str] = mapped_column(String(16), nullable=False, default="v1")
    coeff_code: Mapped[str] = mapped_column(String(64), nullable=False)
    description_vi: Mapped[str] = mapped_column(Text, nullable=False)
    value: Mapped[float] = mapped_column(Float, nullable=False)
    applies_to: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON list of item_codes or "all"
    created_by: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_updated_by: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    last_updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    source_reference: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    effective_date: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    expiry_date: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    approval_status: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    approved_by: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)


class MappingResult(Base):
    """AI semantic mapping output for a BOQ row."""
    __tablename__ = "mapping_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    boq_row_id: Mapped[int] = mapped_column(ForeignKey("boq_rows.id"), nullable=False, unique=True)
    master_item_id: Mapped[Optional[int]] = mapped_column(ForeignKey("master_items.id"), nullable=True)
    status: Mapped[MappingStatus] = mapped_column(Enum(MappingStatus), nullable=False)
    confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    tags_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON dict
    evidence: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    unresolved_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    unit_rule_id: Mapped[Optional[int]] = mapped_column(ForeignKey("unit_rules.id"), nullable=True)
    # Pricing outputs (set by engine, Decimal-precision stored as string)
    unit_price_str: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    extended_amount_str: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    price_source: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    formula_ref: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    coeff_applied_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON list
    master_version: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    pricing_availability: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    price_effective_date: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    price_expiry_date: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    price_source_reference: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    price_last_updated_by: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    price_last_updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    mapping_last_updated_by: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    mapping_last_updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    mapped_by: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    price_review_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    boq_row: Mapped["BOQRow"] = relationship(back_populates="mapping_result")
    master_item: Mapped[Optional["MasterItem"]] = relationship()


class Override(Base):
    """User-recorded overrides on mapping / pricing fields."""
    __tablename__ = "overrides"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id"), nullable=False, index=True)
    row_id: Mapped[str] = mapped_column(String(128), nullable=False)
    field: Mapped[str] = mapped_column(String(64), nullable=False)
    old_value: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    new_value: Mapped[str] = mapped_column(Text, nullable=False)
    user: Mapped[str] = mapped_column(String(128), nullable=False, default="demo-user")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    job: Mapped["Job"] = relationship(back_populates="overrides")


class ConfigurationHistory(Base):
    """Append-only version history for configurable master and pricing records."""
    __tablename__ = "configuration_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    record_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    record_key: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    version: Mapped[str] = mapped_column(String(32), nullable=False)
    event: Mapped[str] = mapped_column(String(64), nullable=False)
    actor: Mapped[str] = mapped_column(String(128), nullable=False)
    change_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ExportRecord(Base):
    """Durable metadata for a generated workbook stored outside the database."""
    __tablename__ = "export_records"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id"), nullable=False, index=True)
    snapshot_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    export_type: Mapped[str] = mapped_column(String(32), nullable=False)
    file_name: Mapped[str] = mapped_column(String(512), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    job: Mapped["Job"] = relationship(back_populates="exports")
