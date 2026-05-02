from abc import ABC, abstractmethod
from pathlib import Path


class BaseDriver(ABC):
    def __init__(self, tenant_id: str):
        self.tenant_id = tenant_id

    @abstractmethod
    def ingest(self, file_path: Path) -> int:
        """Parse and insert records. Returns count inserted."""
        ...
