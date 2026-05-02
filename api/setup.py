import os
import sys
from pathlib import Path
from urllib.parse import quote_plus

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

REQUIRED = ["DB_HOST", "DB_PORT", "DB_USER", "DB_PASSWORD", "DB_NAME", "OPENAI_API_KEY"]


def setup():
    missing = [v for v in REQUIRED if not os.getenv(v)]
    if missing:
        print(f"ERROR: missing env vars: {', '.join(missing)}")
        print("Add them to .env at the repo root and re-run.")
        sys.exit(1)

    import psycopg2
    from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT
    from app.db.connection import get_conn

    db_name = os.getenv("DB_NAME")
    admin_url = (
        f"postgresql://{quote_plus(os.getenv('DB_USER'))}:{quote_plus(os.getenv('DB_PASSWORD'))}"
        f"@{os.getenv('DB_HOST')}:{os.getenv('DB_PORT')}/postgres"
    )

    conn = psycopg2.connect(admin_url)
    conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (db_name,))
        if cur.fetchone():
            print(f"Dropping '{db_name}'...")
            cur.execute(f'DROP DATABASE "{db_name}"')
        print(f"Creating '{db_name}'...")
        cur.execute(f'CREATE DATABASE "{db_name}"')
    conn.close()

    print("Running migrations...")
    conn = psycopg2.connect(
        f"postgresql://{quote_plus(os.getenv('DB_USER'))}:{quote_plus(os.getenv('DB_PASSWORD'))}"
        f"@{os.getenv('DB_HOST')}:{os.getenv('DB_PORT')}/{db_name}"
    )
    for sql_file in sorted(Path(__file__).parent.glob("migrations/*.sql")):
        print(f"  {sql_file.name}")
        with conn.cursor() as cur:
            cur.execute(sql_file.read_text())
        conn.commit()
    conn.close()

    print("Done.")


if __name__ == "__main__":
    setup()
