"""The claim itself, at the row-locking level: two claimers never get the same message."""

from app.dispatch import claim_next
from tests.worker.conftest import queue


def test_claim_skips_rows_locked_by_another_claimer(session_factory, commit, ana, device):
    first, second = queue(commit, ana, "a"), queue(commit, ana, "b")
    with session_factory() as holder, session_factory() as other:
        held = claim_next(holder, device)
        assert held.id == first  # claimed but not committed: the row stays locked
        taken = claim_next(other, device)
        assert taken.id == second  # SKIP LOCKED passes over the locked row
        other.commit()
        assert claim_next(other, device) is None
        holder.rollback()


def test_reaping_expired_leases_does_not_block_other_claimers(
    session_factory, commit, ana, device
):
    """The reaper once took range locks that blocked (and deadlocked) other workers' lease inserts.
    Hold its locks open in one session and claim in another: the claim must go straight through."""
    from sqlalchemy import text

    from app.dispatch import expire_leases

    queue(commit, ana, "a")
    with session_factory() as reaper, session_factory() as claimer:
        expire_leases(reaper)  # no commit: whatever locks it took stay held
        claimer.execute(text("SET SESSION innodb_lock_wait_timeout = 2"))
        assert claim_next(claimer, device) is not None
        claimer.commit()
        reaper.rollback()
