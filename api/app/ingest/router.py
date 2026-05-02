from pathlib import Path

from .drivers.appointments import AppointmentsDriver
from .drivers.claims import ClaimsDriver
from .drivers.data_sources import DataSourcesDriver
from .drivers.base import BaseDriver

_TABLE_DRIVERS = {
    "appointments": AppointmentsDriver,
    "claims":       ClaimsDriver,
}


def get_driver(table: str, tenant_id: str, **kwargs) -> BaseDriver:
    if table in _TABLE_DRIVERS:
        return _TABLE_DRIVERS[table](tenant_id)
    return DataSourcesDriver(tenant_id, **kwargs)
