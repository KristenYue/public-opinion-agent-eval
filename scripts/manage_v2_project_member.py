"""Provision or change a Project member through a trusted deployment shell.

This is intentionally not a public HTTP administration endpoint.  Operators
run it with database credentials supplied by their deployment secret manager.
"""

from __future__ import annotations

import argparse
import os
from uuid import UUID


ROLES = ("owner", "analyst", "viewer")


def _database_url() -> str:
    value = os.getenv("DATABASE_URL", "").strip()
    if not value:
        raise SystemExit("DATABASE_URL is required")
    return value


def main() -> None:
    parser = argparse.ArgumentParser(description="Grant a V2 Project role")
    parser.add_argument("project_id", type=UUID)
    parser.add_argument("subject")
    parser.add_argument("role", choices=ROLES)
    args = parser.parse_args()
    subject = args.subject.strip()
    if not subject or len(subject) > 200:
        raise SystemExit("subject must contain 1 to 200 characters")

    try:
        import psycopg
    except ImportError as exc:
        raise SystemExit("Install production dependencies with: pip install -e '.[production]'") from exc

    with psycopg.connect(_database_url()) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO project_members (project_id, subject, role)
                VALUES (%s, %s, %s)
                ON CONFLICT (project_id, subject) DO UPDATE SET role = EXCLUDED.role
                """,
                (args.project_id, subject, args.role),
            )
        connection.commit()
    print(f"Project role applied: project={args.project_id} subject={subject} role={args.role}")


if __name__ == "__main__":
    main()
