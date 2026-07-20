"""Curator visibility scope for students pinned to a specific curator."""

from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True, slots=True)
class StaffScope:
    """Identifies the staff member reading data, for pinned-student filtering.

    Admins always see everything. A non-admin only sees students who are
    unpinned or pinned to them.
    """

    staff_id: UUID
    is_admin: bool
