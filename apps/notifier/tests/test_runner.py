"""The notifier's loop: sends what the API queued in push_outbox, retries, and tells the others
first. Runs against a real MySQL built from contract/outbox.sql."""

import json
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from comm_center_notifier import outbox, runner, sender
from comm_center_notifier.config import settings

NOW = datetime(2026, 11, 9, 8, 0, 0)


@pytest.fixture(autouse=True)
def configured(monkeypatch):
    monkeypatch.setattr(settings, "vapid_public_key", "pub")
    monkeypatch.setattr(settings, "vapid_private_key", "priv")
    monkeypatch.setattr(settings, "vapid_subject", "mailto:admin@example.com")
    monkeypatch.setattr(settings, "push_retry_base_seconds", 30)
    monkeypatch.setattr(settings, "push_max_attempts", 4)
    monkeypatch.setattr(settings, "notifier_lease_seconds", 60)


@pytest.fixture
def sent(monkeypatch):
    """Every push attempted, as (endpoint, payload). ``fail`` maps an endpoint to what its send
    raises; ``during`` is called with the endpoint while the send is in progress."""

    class Sent(list):
        def __init__(self):
            super().__init__()
            self.fail: dict = {}
            self.during = None

    log = Sent()

    def fake(target, payload):
        log.append((target.endpoint, payload))
        if log.during:
            log.during(target.endpoint)
        if target.endpoint in log.fail:
            raise log.fail[target.endpoint]

    monkeypatch.setattr(sender, "send_push", fake)
    return log


_n = iter(range(1, 10_000))


def insert(db, table, **cols):
    names = ", ".join(cols)
    marks = ", ".join(["%s"] * len(cols))
    with db.cursor() as cur:
        cur.execute(f"INSERT INTO {table} ({names}) VALUES ({marks})", list(cols.values()))
        return cur.lastrowid


def add(db, count=1, senders=("Maria",), send_after=NOW, state="pending", attempts=0, **cols):
    """A subscription with one row in the outbox. Returns (subscription id, row id, endpoint)."""
    n = next(_n)
    endpoint = f"https://push.example.com/send/{n}"
    sub = insert(
        db, "push_subscription", user_id=n, endpoint=endpoint, endpoint_hash=f"{n:064d}",
        p256dh="k", auth="a",
    )  # fmt: skip
    row = insert(
        db, "push_outbox", subscription_id=sub, state=state, message_count=count,
        last_message_id=100 + n, senders=json.dumps(list(senders)), send_after=send_after,
        attempts=attempts, **cols,
    )  # fmt: skip
    return sub, row, endpoint


def api_adds(db, subscription_id, message_id, sender_name, now):
    """What the API does when a message arrives (the contract's rule): join the pending row, or
    start one."""
    with db.cursor() as cur:
        cur.execute(
            "SELECT id, senders FROM push_outbox WHERE subscription_id=%s AND state='pending'",
            [subscription_id],
        )
        row = cur.fetchone()
        if row:
            names = json.loads(row["senders"])
            if sender_name not in names:
                names.append(sender_name)
            cur.execute(
                "UPDATE push_outbox SET message_count=message_count+1, last_message_id=%s, "
                "senders=%s WHERE id=%s",
                [message_id, json.dumps(names), row["id"]],
            )
        else:
            cur.execute(
                "INSERT INTO push_outbox (subscription_id, state, message_count, last_message_id, "
                "senders, send_after) VALUES (%s, 'pending', 1, %s, %s, %s)",
                [subscription_id, message_id, json.dumps([sender_name]), now],
            )


def rows(db):
    with db.cursor() as cur:
        cur.execute(
            "SELECT s.endpoint, o.state, o.attempts, o.send_after, o.message_count, o.last_error "
            "FROM push_outbox o JOIN push_subscription s ON s.id = o.subscription_id"
        )
        return {r["endpoint"]: SimpleNamespace(**r) for r in cur.fetchall()}


def subscriptions(db):
    with db.cursor() as cur:
        cur.execute("SELECT endpoint FROM push_subscription")
        return {r["endpoint"] for r in cur.fetchall()}


# --- sending --------------------------------------------------------------------------------


def test_a_due_notification_is_sent_and_removed(db, connect, sent):
    _, _, endpoint = add(db, senders=("Maria Santos",))
    runner.run_once(connect, NOW)
    assert sent == [
        (endpoint, {"title": "New message", "body": "From Maria Santos", "url": "/messages?direction=received", "tag": sent[0][1]["tag"]})
    ]
    assert rows(db) == {} and subscriptions(db) == {endpoint}


def test_a_notification_inside_its_aggregation_window_waits(db, connect, sent):
    add(db, send_after=NOW + timedelta(seconds=5))
    runner.run_once(connect, NOW)
    assert sent == []
    runner.run_once(connect, NOW + timedelta(seconds=5))
    assert len(sent) == 1


def test_several_messages_are_one_notification(db, connect, sent):
    add(db, count=3, senders=("Maria", "Jose"))
    runner.run_once(connect, NOW)
    [(_, payload)] = sent
    assert (payload["title"], payload["body"]) == ("3 new messages", "From Maria and Jose")


def test_the_row_is_marked_sending_while_the_push_is_in_flight(db, connect, sent):
    _, _, endpoint = add(db)
    seen = {}
    sent.during = lambda e: seen.update(rows(db))
    runner.run_once(connect, NOW)
    assert seen[endpoint].state == "sending"


def test_a_message_arriving_during_the_send_starts_a_new_notification(db, connect, sent):
    sub, _, endpoint = add(db)

    def arrives(_):
        api_adds(db, sub, 999, "Jose", NOW)

    sent.during = arrives
    runner.run_once(connect, NOW)
    left = rows(db)
    assert list(left) == [endpoint] and left[endpoint].state == "pending" and left[endpoint].message_count == 1


# --- failures -------------------------------------------------------------------------------


def test_a_temporary_failure_is_planned_for_a_retry(db, connect, sent):
    _, _, endpoint = add(db)
    sent.fail = {endpoint: sender.PushError("push service answered 503")}
    runner.run_once(connect, NOW)
    row = rows(db)[endpoint]
    assert (row.state, row.attempts, row.send_after) == ("pending", 1, NOW + timedelta(seconds=30))
    assert "503" in row.last_error and subscriptions(db) == {endpoint}


def test_the_retry_happens_when_due_and_clears_the_row(db, connect, sent):
    _, _, endpoint = add(db)
    sent.fail = {endpoint: sender.PushError("503")}
    runner.run_once(connect, NOW)
    sent.clear()
    runner.run_once(connect, NOW + timedelta(seconds=29))
    assert sent == []
    sent.fail = {}
    runner.run_once(connect, NOW + timedelta(seconds=30))
    assert len(sent) == 1 and rows(db) == {}


def test_each_retry_waits_longer(db, connect, sent):
    _, _, endpoint = add(db)
    sent.fail = {endpoint: sender.PushError("503")}
    t = NOW
    waits = []
    for _ in range(3):
        runner.run_once(connect, t)
        waits.append((rows(db)[endpoint].send_after - t).total_seconds())
        t = rows(db)[endpoint].send_after
    assert waits == [30, 60, 120]


def test_it_gives_up_after_the_last_attempt_but_keeps_the_subscription(db, connect, sent):
    _, _, endpoint = add(db)
    sent.fail = {endpoint: sender.PushError("503")}
    t = NOW
    for _ in range(4):  # push_max_attempts
        runner.run_once(connect, t)
        t += timedelta(hours=1)
    assert len(sent) == 4 and rows(db) == {} and subscriptions(db) == {endpoint}


def test_a_failing_recipient_does_not_hold_up_the_others(db, connect, sent):
    _, _, bad = add(db)
    _, _, good = add(db)
    sent.fail = {bad: sender.PushError("503")}
    runner.run_once(connect, NOW)
    assert {e for e, _ in sent} == {bad, good}
    assert set(rows(db)) == {bad}


def test_others_are_sent_before_a_retry(db, connect, sent):
    _, _, bad = add(db)
    sent.fail = {bad: sender.PushError("503")}
    runner.run_once(connect, NOW)
    sent.clear()
    _, _, newcomer = add(db, send_after=NOW + timedelta(seconds=1))
    runner.run_once(connect, NOW + timedelta(seconds=1))
    assert [e for e, _ in sent] == [newcomer]  # the retry is not due until later
    assert set(rows(db)) == {bad}


def test_a_due_retry_goes_after_notifications_that_are_waiting_longer_to_go_out_first(db, connect, sent):
    _, _, retry = add(db, send_after=NOW + timedelta(seconds=30), attempts=1)
    _, _, fresh = add(db, send_after=NOW + timedelta(seconds=10))
    runner.run_once(connect, NOW + timedelta(seconds=60))
    assert [e for e, _ in sent] == [fresh, retry]  # oldest send_after first


def test_a_subscription_the_service_forgot_is_deleted_with_its_row(db, connect, sent):
    _, _, gone = add(db)
    _, _, keep = add(db)
    sent.fail = {gone: sender.PushGone("410")}
    runner.run_once(connect, NOW)
    assert subscriptions(db) == {keep} and rows(db) == {}


def test_a_rejection_is_not_retried_and_does_not_delete_the_subscription(db, connect, sent):
    _, _, endpoint = add(db)
    sent.fail = {endpoint: sender.PushRejected("push service answered 403")}
    runner.run_once(connect, NOW)
    assert rows(db) == {} and subscriptions(db) == {endpoint}
    sent.clear()
    runner.run_once(connect, NOW + timedelta(hours=1))
    assert sent == []


def test_an_unexpected_error_counts_as_a_temporary_failure(db, connect, sent):
    _, _, endpoint = add(db)
    sent.fail = {endpoint: RuntimeError("boom")}
    runner.run_once(connect, NOW)
    assert rows(db)[endpoint].attempts == 1


# --- aggregation while waiting --------------------------------------------------------------


def test_a_message_arriving_while_a_retry_waits_joins_it(db, connect, sent):
    sub, _, endpoint = add(db, senders=("Maria",))
    sent.fail = {endpoint: sender.PushError("503")}
    runner.run_once(connect, NOW)  # fails: waits until NOW + 30s
    api_adds(db, sub, 500, "Jose", NOW + timedelta(seconds=10))
    assert rows(db)[endpoint].message_count == 2 and len(rows(db)) == 1
    sent.clear()
    sent.fail = {}
    runner.run_once(connect, NOW + timedelta(seconds=30))
    [(_, payload)] = sent
    assert (payload["title"], payload["body"]) == ("2 new messages", "From Maria and Jose")


def test_a_failed_row_that_finds_a_newer_one_merges_into_it(db, connect):
    sub, sending, _ = add(db, count=2, senders=("Maria",), state="sending", attempts=1, lease_until=NOW)
    pending = insert(
        db, "push_outbox", subscription_id=sub, state="pending", message_count=1,
        last_message_id=900, senders=json.dumps(["Jose"]), send_after=NOW, attempts=0,
    )  # fmt: skip
    conn = connect()
    outbox.requeue(conn, outbox.get(conn, sending), NOW + timedelta(seconds=60), "503")
    conn.commit()
    with db.cursor() as cur:
        cur.execute("SELECT id, message_count, attempts, senders, last_message_id FROM push_outbox")
        [only] = cur.fetchall()
    assert only["id"] == pending and only["message_count"] == 3 and only["attempts"] == 1
    assert json.loads(only["senders"]) == ["Jose", "Maria"] and only["last_message_id"] == 900


# --- crashes and configuration --------------------------------------------------------------


def test_a_row_whose_lease_ran_out_is_sent_again(db, connect, sent):
    """The notifier died after claiming it: nothing is lost (at least once)."""
    _, _, endpoint = add(db, state="sending", lease_until=NOW - timedelta(seconds=1))
    runner.run_once(connect, NOW)
    assert [e for e, _ in sent] == [endpoint] and rows(db) == {}


def test_a_row_still_leased_is_left_alone(db, connect, sent):
    add(db, state="sending", lease_until=NOW + timedelta(seconds=30))
    runner.run_once(connect, NOW)
    assert sent == []


def test_nothing_is_sent_while_push_is_not_configured(db, connect, sent, monkeypatch):
    add(db)
    monkeypatch.setattr(settings, "vapid_private_key", "")
    runner.run_once(connect, NOW)
    assert sent == [] and len(rows(db)) == 1


def test_the_loop_beats_every_cycle_and_survives_an_error(connect, monkeypatch):
    calls, beats = [], []

    def run(factory_, now):
        calls.append(now)
        if len(calls) == 2:
            raise RuntimeError("database went away")
        return 0

    monkeypatch.setattr(runner, "run_once", run)
    runner.run_loop(connect, heartbeat=lambda: beats.append(1), sleep=lambda s: None, stop=lambda: len(calls) >= 4)
    assert len(calls) == 4 and len(beats) >= 3
