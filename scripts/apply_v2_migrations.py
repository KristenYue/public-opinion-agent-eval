"""Apply the frozen V2 PostgreSQL baseline migration.

This intentionally has no silent SQLite fallback: running V2 against a
different database would invalidate the JSONB, UUID, constraint and locking
assumptions exercised by the production repository.
"""

from importlib.resources import files
import os


def main() -> None:
    database_url = os.getenv("DATABASE_URL", "").strip()
    if not database_url:
        raise SystemExit("DATABASE_URL is required")
    try:
        import psycopg
    except ImportError as exc:
        raise SystemExit("Install production dependencies with: pip install -e '.[production]'") from exc

    with psycopg.connect(database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version VARCHAR(200) PRIMARY KEY,
                    applied_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
        connection.commit()

    migration_root = files("opinion_agent").joinpath("v2/migrations")
    migrations = sorted(
        (item for item in migration_root.iterdir() if item.name.endswith(".sql")),
        key=lambda item: item.name,
    )
    for migration_file in migrations:
        with psycopg.connect(database_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT 1 FROM schema_migrations WHERE version = %s",
                    (migration_file.name,),
                )
                if cursor.fetchone():
                    print(f"Already applied: {migration_file.name}")
                    continue
                cursor.execute(migration_file.read_text(encoding="utf-8"))
                cursor.execute(
                    "INSERT INTO schema_migrations (version) VALUES (%s)",
                    (migration_file.name,),
                )
            connection.commit()
        print(f"Applied V2 migration: {migration_file.name}")


if __name__ == "__main__":
    main()
