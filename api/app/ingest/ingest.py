from pathlib import Path

from .router import get_driver


def ingest_file(
    file_path: str | Path,
    tenant_id: str,
    table: str,
    **kwargs,
) -> int:
    path = Path(file_path)
    driver = get_driver(table, tenant_id, **kwargs)
    print(f"[ingest] {path.name} → {driver.__class__.__name__} (tenant={tenant_id})")
    return driver.ingest(path)
