"""Alembic environment for the single local SQLite database."""

from alembic import context
from sqlalchemy import text

from app.db import models  # noqa: F401 - register all tables
from app.db.database import Base, engine


def run_migrations_online() -> None:
    with engine.connect() as connection:
        # SQLite batch replacement of notes must not cascade-delete children.
        connection.execute(text("PRAGMA foreign_keys=OFF"))
        connection.commit()
        try:
            context.configure(connection=connection, target_metadata=Base.metadata, compare_type=True)
            with context.begin_transaction():
                context.run_migrations()
            if connection.execute(text("PRAGMA foreign_key_check")).fetchall():
                raise RuntimeError("Migration left invalid foreign keys; restore the pre-migration checkpoint")
            connection.commit()
        finally:
            connection.rollback()
            connection.execute(text("PRAGMA foreign_keys=ON"))
            connection.commit()


if context.is_offline_mode():
    raise RuntimeError("Offline migrations are not supported for the local SQLite database")
run_migrations_online()
