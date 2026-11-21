"""The run-state vocabulary from DESIGN.md section 6, and its only definition.

Any module that names a state imports it here. T09 persists these values; a run
that needs a new state adds one to this enum first, never a bare string.
"""

from __future__ import annotations

from enum import StrEnum


class RunState(StrEnum):
    new = "new"
    triaged = "triaged"
    diagnosed = "diagnosed"
    verified = "verified"
    fix_proposed = "fix_proposed"
    critiqued = "critiqued"
    awaiting_approval = "awaiting_approval"
    approved = "approved"
    rejected = "rejected"
    executed = "executed"
    done = "done"
    escalated = "escalated"
    failed = "failed"
