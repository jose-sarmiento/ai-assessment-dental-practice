from pathlib import Path

from .base import BaseDriver


class ClaimsDriver(BaseDriver):

    def ingest(self, file_path: Path) -> int:
        # TODO: implement claims ingestion
        print(f"[claims] not yet implemented — skipping {file_path.name}")
        return 0
