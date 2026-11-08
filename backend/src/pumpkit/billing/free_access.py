from dataclasses import dataclass
from datetime import datetime

from pumpkit.billing.models import FreeAccess
from pumpkit.core.time import as_utc


@dataclass(frozen=True)
class FreeAccessCoverage:
    starts_at: datetime
    ends_at: datetime
    months: int
    grants: tuple[FreeAccess, ...]

    def grant_at(self, moment: datetime) -> FreeAccess:
        return next(
            (
                grant
                for grant in self.grants
                if as_utc(grant.starts_at) <= moment < as_utc(grant.ends_at)
            ),
            self.grants[-1],
        )
