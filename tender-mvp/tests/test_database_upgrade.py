import sys
from pathlib import Path

from sqlalchemy import create_engine, inspect, text

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from database import _ensure_legacy_columns, _ensure_nullable_master_prices


def test_legacy_sqlite_upgrade_preserves_uat_rows_and_foreign_keys(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'legacy.db'}")
    with engine.begin() as connection:
        connection.execute(text("PRAGMA foreign_keys=ON"))
        connection.execute(text("""
            CREATE TABLE master_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT, tenant_id VARCHAR(64) NOT NULL,
                version VARCHAR(16) NOT NULL, item_code VARCHAR(64) NOT NULL,
                description_vi TEXT NOT NULL, unit VARCHAR(64) NOT NULL,
                unit_price FLOAT NOT NULL, formula_ref VARCHAR(128), source_sheet VARCHAR(128), tags_json TEXT
            )
        """))
        connection.execute(text("""
            CREATE TABLE unit_rules (
                id INTEGER PRIMARY KEY, version VARCHAR(16) NOT NULL, from_unit VARCHAR(64) NOT NULL,
                to_unit VARCHAR(64) NOT NULL, factor FLOAT NOT NULL, note VARCHAR(256)
            )
        """))
        connection.execute(text("""
            CREATE TABLE coefficients (
                id INTEGER PRIMARY KEY, version VARCHAR(16) NOT NULL, coeff_code VARCHAR(64) NOT NULL,
                description_vi TEXT NOT NULL, value FLOAT NOT NULL, applies_to TEXT
            )
        """))
        connection.execute(text("""
            CREATE TABLE mapping_results (
                id INTEGER PRIMARY KEY, boq_row_id INTEGER NOT NULL UNIQUE,
                master_item_id INTEGER REFERENCES master_items(id), status VARCHAR(64) NOT NULL,
                confidence FLOAT, tags_json TEXT, evidence TEXT, unresolved_reason TEXT,
                unit_rule_id INTEGER, unit_price_str VARCHAR(64), extended_amount_str VARCHAR(64),
                price_source VARCHAR(64), formula_ref VARCHAR(128), coeff_applied_json TEXT,
                master_version VARCHAR(16)
            )
        """))
        connection.execute(text("""
            INSERT INTO master_items
              (id, tenant_id, version, item_code, description_vi, unit, unit_price, formula_ref, source_sheet, tags_json)
            VALUES (7, 'uat', 'v1', 'KS-UAT', 'Preserved UAT item', 'm', 12345, 'F1', 'Evidence', '{}')
        """))
        connection.execute(text("""
            INSERT INTO mapping_results
              (id, boq_row_id, master_item_id, status, unit_price_str, extended_amount_str, price_source, master_version)
            VALUES (9, 11, 7, 'mapped_and_priced', '12345', '24690', 'master_data', 'v1')
        """))

        _ensure_legacy_columns(connection)

    with engine.connect() as connection:
        _ensure_nullable_master_prices(connection)

        master = connection.execute(text("SELECT id, item_code, unit_price, description_vi FROM master_items")).one()
        mapping = connection.execute(text("SELECT id, master_item_id, unit_price_str FROM mapping_results")).one()
        assert tuple(master) == (7, "KS-UAT", 12345.0, "Preserved UAT item")
        assert tuple(mapping) == (9, 7, "12345")
        assert connection.execute(text("PRAGMA foreign_key_check")).all() == []
        nullable = {column["name"]: column["nullable"] for column in inspect(connection).get_columns("master_items")}
        assert nullable["unit_price"] is True
        connection.execute(text("UPDATE master_items SET unit_price = NULL WHERE id = 7"))
        assert connection.execute(text("SELECT unit_price FROM master_items WHERE id = 7")).scalar_one() is None
