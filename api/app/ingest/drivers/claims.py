import csv
from pathlib import Path

from psycopg2.extras import execute_values

from ...db.connection import get_conn
from .base import BaseDriver


class ClaimsDriver(BaseDriver):

    def ingest(self, file_path: Path) -> int:
        rows = self._parse(file_path)
        if not rows:
            return 0
        self._insert(rows)
        return len(rows)

    def _parse(self, file_path: Path) -> list[dict]:
        rows = []
        with file_path.open(newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                rows.append({
                    "claim_id":        row["claim_id"],
                    "patient_id":      row["patient_id"],
                    "patient_name":    row["patient_name"],
                    "date_of_service": row["date_of_service"],
                    "procedure_code":  row.get("procedure_code", ""),
                    "procedure_desc":  row.get("procedure_desc", ""),
                    "billed_amount":   _decimal(row.get("billed_amount")),
                    "insurance_paid":  _decimal(row.get("insurance_paid")),
                    "patient_owed":    _decimal(row.get("patient_owed")),
                    "status":          row.get("status", "pending"),
                    "payer":           row.get("payer", ""),
                    "notes":           row.get("notes", ""),
                    "tenant_id":       row.get("tenant_id") or self.tenant_id,
                })
        return rows

    def _insert(self, rows: list[dict]) -> None:
        sql = """
            INSERT INTO claims (
                claim_id, patient_id, patient_name, date_of_service,
                procedure_code, procedure_desc,
                billed_amount, insurance_paid, patient_owed,
                status, payer, notes, tenant_id
            ) VALUES %s
            ON CONFLICT DO NOTHING
        """
        values = [
            (
                r["claim_id"], r["patient_id"], r["patient_name"], r["date_of_service"],
                r["procedure_code"], r["procedure_desc"],
                r["billed_amount"], r["insurance_paid"], r["patient_owed"],
                r["status"], r["payer"], r["notes"], r["tenant_id"],
            )
            for r in rows
        ]
        conn = get_conn()
        try:
            execute_values(conn.cursor(), sql, values)
            conn.commit()
        finally:
            conn.close()


def _decimal(value: str | None):
    try:
        return float(value) if value else None
    except ValueError:
        return None
