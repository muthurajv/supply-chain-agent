from dataclasses import dataclass
from datetime import datetime


@dataclass
class KPIRecord:
    name: str
    value: float
    unit: str
    narrative: str
    computed_at: datetime
