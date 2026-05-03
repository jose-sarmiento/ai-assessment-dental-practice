import csv
import re
from pathlib import Path

from psycopg2.extras import execute_values

from ...db.connection import get_conn
from .base import BaseDriver


class AppointmentsDriver(BaseDriver):

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
                procedure_code, procedure_desc = _split_procedure(row.get("procedure", ""))
                rows.append({
                    "appointment_id": row["appointment_id"],
                    "patient_name":   row["patient_name"],
                    "patient_id":     row["patient_id"],
                    "provider":       row["provider"],
                    "date":           row["date"],
                    "time":           row["time"],
                    "procedure_code": procedure_code,
                    "procedure_desc": procedure_desc,
                    "status":         row.get("status", "scheduled"),
                    "notes":          row.get("notes", ""),
                    "tenant_id":      row.get("tenant_id") or self.tenant_id,
                })
        return rows

    def _insert(self, rows: list[dict]) -> None:
        sql = """
            INSERT INTO appointments (
                appointment_id, patient_name, patient_id, provider,
                date, time, procedure_code, procedure_desc,
                status, notes, tenant_id
            ) VALUES %s
            ON CONFLICT DO NOTHING
        """
        values = [
            (
                r["appointment_id"], r["patient_name"], r["patient_id"], r["provider"],
                r["date"], r["time"], r["procedure_code"], r["procedure_desc"],
                r["status"], r["notes"], r["tenant_id"],
            )
            for r in rows
        ]
        conn = get_conn()
        try:
            execute_values(conn.cursor(), sql, values)
            conn.commit()
        finally:
            conn.close()


def _split_procedure(value: str) -> tuple[str, str]:
    """'Composite Filling D2391' → ('D2391', 'Composite Filling')"""
    match = re.search(r'\b([A-Z]\d{4})\b', value)
    if match:
        code = match.group(1)
        desc = value.replace(code, "").strip()
        return code, desc
    return "", value.strip()
