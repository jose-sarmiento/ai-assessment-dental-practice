import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")
sys.path.insert(0, str(Path(__file__).parent))

from app.ingest.ingest import ingest_file

TENANT_ID = "clinic-demo"

FILES = [
    ("mock_data/appointments.csv", "appointments"),
    ("mock_data/claims.csv",       "claims"),
    ("mock_data/insurance_faq.txt", "data_sources", {"doc_type": "faq"}),
]

for entry in FILES:
    file_path, table = entry[0], entry[1]
    kwargs = entry[2] if len(entry) > 2 else {}
    ingest_file(file_path, tenant_id=TENANT_ID, table=table, **kwargs)
