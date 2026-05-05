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
        sys.exit(1)

    import psycopg2
    from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT

    db_name   = os.getenv("DB_NAME")
    fresh     = "--fresh" in sys.argv
    admin_url = (
        f"postgresql://{quote_plus(os.getenv('DB_USER'))}:{quote_plus(os.getenv('DB_PASSWORD'))}"
        f"@{os.getenv('DB_HOST')}:{os.getenv('DB_PORT')}/postgres"
    )

    conn = psycopg2.connect(admin_url)
    conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (db_name,))
        exists = cur.fetchone()

        if exists and not fresh:
            print(f"Database '{db_name}' already exists. Setup has already been run.")
            print(f"To drop and recreate, run: docker compose exec api python setup.py --fresh")
            print(f"Note: --fresh will require restarting the API after: docker compose restart api")
            sys.exit(0)

        if exists and fresh:
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

    print("\nRunning ingest...")
    from app.ingest.ingest import ingest_file

    FILE_TABLE_MAP = {
        "appointments.csv": "appointments",
        "claims.csv":       "claims",
    }
    AUDIENCE_DIRS = {"staff", "patient", "all"}

    mock_root = Path(__file__).parent / "mock_data"
    for clinic_dir in sorted(mock_root.iterdir()):
        if not clinic_dir.is_dir():
            continue
        tenant_id = clinic_dir.name
        for entry in sorted(clinic_dir.iterdir()):
            if entry.is_dir() and entry.name in AUDIENCE_DIRS:
                audience = entry.name
                for file_path in sorted(entry.iterdir()):
                    ingest_file(str(file_path), tenant_id=tenant_id, table="data_sources", audience=audience)
            elif entry.is_file():
                table = FILE_TABLE_MAP.get(entry.name, "data_sources")
                ingest_file(str(entry), tenant_id=tenant_id, table=table)

    print("Ingest complete.")

    if fresh:
        print("\nRestart the API to restore the database connection:")
        print("  docker compose restart api")



if __name__ == "__main__":
    setup()
