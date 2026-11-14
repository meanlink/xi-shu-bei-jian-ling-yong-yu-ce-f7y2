from sqlalchemy import inspect, text
from src.config.database import Base, engine
from src import models


ADDED_COLUMNS = {
    'datasets': [('quarantined', 'BOOLEAN NOT NULL DEFAULT FALSE')],
    'jobs': [('quarantined', 'BOOLEAN NOT NULL DEFAULT FALSE')],
    'reports': [('quarantined', 'BOOLEAN NOT NULL DEFAULT FALSE'), ('quarantine_id', 'INTEGER')],
    'deliveries': [('quarantined', 'BOOLEAN NOT NULL DEFAULT FALSE'), ('quarantine_id', 'INTEGER')],
}


def _add_missing_columns():
    """Additive upgrade for databases created before quarantine support.

    create_all() only creates missing tables, so an existing deployment needs
    the new columns added in place. Defaults keep prior rows readable as
    "not quarantined", and no historical data is rewritten.
    """
    existing = inspect(engine)
    tables = set(existing.get_table_names())
    with engine.begin() as conn:
        for table, columns in ADDED_COLUMNS.items():
            if table not in tables:
                continue
            present = {c['name'] for c in existing.get_columns(table)}
            for name, ddl in columns:
                if name not in present:
                    conn.execute(text(f'ALTER TABLE {table} ADD COLUMN {name} {ddl}'))


def migrate():
    Base.metadata.create_all(engine)
    _add_missing_columns()


if __name__ == '__main__':
    migrate()
