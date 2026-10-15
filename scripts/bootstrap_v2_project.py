"""Create the explicit project required by the V2 job foreign key."""

import os
from uuid import UUID


DEFAULT_PROJECT_ID = "11111111-1111-1111-1111-111111111111"


def _required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise SystemExit(f"{name} is required")
    return value


def main() -> None:
    database_url = _required("DATABASE_URL")
    project_id = UUID(os.getenv("V2_PROJECT_ID", DEFAULT_PROJECT_ID).strip())
    project_name = os.getenv("V2_PROJECT_NAME", "Local V2 Project").strip()
    created_by = os.getenv("V2_PROJECT_CREATED_BY", "bootstrap").strip()
    if not project_name or not created_by:
        raise SystemExit("V2_PROJECT_NAME and V2_PROJECT_CREATED_BY must not be blank")

    try:
        import psycopg
    except ImportError as exc:
        raise SystemExit(
            "Install production dependencies with: pip install -e '.[production]'"
        ) from exc

    with psycopg.connect(database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO projects (id, name, description, created_by)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (id) DO NOTHING
                """,
                (
                    project_id,
                    project_name,
                    "Idempotently created by the V2 deployment bootstrap.",
                    created_by,
                ),
            )
        connection.commit()
    print(f"V2 project ready: {project_id}")


if __name__ == "__main__":
    main()
