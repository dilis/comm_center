from datetime import datetime

from sqlalchemy import text

from app import inbound as shared
from app.inbound import ingest_message
from app.worker.provider import InboundSms
from tests.db.helpers import make_contact, make_phone


def sms(sender="+639171234567", content="hi", ref="1"):
    return InboundSms(
        ref=ref, sender=sender, content=content, received_at=datetime(2026, 1, 2, 3, 4, 5)
    )


def ingest_committed(session_factory, device, message):
    with session_factory() as db:
        result = ingest_message(
            db, device.agent_user_id, message.sender, message.content, message.received_at
        )
        db.commit()
        return result


def q(session_factory, sql, **params):
    with session_factory() as db:
        return db.execute(text(sql), params).all()


def test_unknown_sender_gets_a_contact_owned_by_the_device_agent(session_factory, device):
    m = ingest_committed(session_factory, device, sms(content="hello there"))
    msg = q(session_factory, "SELECT * FROM messages WHERE id=:i", i=m.id)[0]
    assert (msg.status, msg.owner_id, msg.content) == (
        "received",
        device.agent_user_id,
        "hello there",
    )
    assert msg.phone_number == "+639171234567" and msg.received_at == datetime(2026, 1, 2, 3, 4, 5)
    assert msg.gsm_device_id is None  # inbound: derived from the owner
    contact = q(session_factory, "SELECT * FROM contacts WHERE id=:i", i=msg.contact_id)[0]
    assert (contact.name, contact.owner_id, contact.type) == (
        "+639171234567",
        device.agent_user_id,
        "person",
    )
    phones = q(
        session_factory, "SELECT phone_e164 FROM contact_phone WHERE contact_id=:c", c=contact.id
    )
    assert [p.phone_e164 for p in phones] == ["+639171234567"]
    # auto-created: owned by a system agent and linked to no user
    assert not q(session_factory, "SELECT id FROM users WHERE contact_id=:c", c=contact.id)


def test_known_sender_reuses_the_contact_whatever_the_number_format(
    session_factory, commit, device
):
    cid = commit(make_contact, "Ana")
    commit(make_phone, cid, "+639171234567")
    m1 = ingest_committed(session_factory, device, sms(sender="0917 123 4567"))
    m2 = ingest_committed(session_factory, device, sms(sender="+639171234567"))
    assert m1.contact_id == m2.contact_id == cid
    assert (
        q(session_factory, "SELECT COUNT(*) AS n FROM contacts WHERE name='+639171234567'")[0].n
        == 0
    )


def test_second_message_from_a_new_sender_reuses_the_auto_created_contact(session_factory, device):
    m1 = ingest_committed(session_factory, device, sms())
    m2 = ingest_committed(session_factory, device, sms(content="again"))
    assert m1.contact_id == m2.contact_id


def test_a_soft_deleted_contacts_number_gets_a_new_contact(session_factory, commit, device):
    old = commit(make_contact, "Old")
    commit(make_phone, old, "+639171234567")
    with session_factory() as db:
        db.execute(
            text("UPDATE contact_phone SET deleted_at=NOW() WHERE contact_id=:c"), {"c": old}
        )
        db.execute(text("UPDATE contacts SET deleted_at=NOW() WHERE id=:c"), {"c": old})
        db.commit()
    m = ingest_committed(session_factory, device, sms())
    assert m.contact_id != old


def test_duplicate_key_race_rereads_the_winners_contact(
    session_factory, commit, device, monkeypatch
):
    winner = commit(make_contact, "Winner")
    commit(make_phone, winner, "+639171234567")
    real = shared.find_contact_id
    calls = []

    def blind_first_time(db, number):
        calls.append(number)
        return None if len(calls) == 1 else real(db, number)

    monkeypatch.setattr(shared, "find_contact_id", blind_first_time)
    m = ingest_committed(session_factory, device, sms())
    assert len(calls) == 2 and m.contact_id == winner
    # the losing attempt left no orphan contact behind
    assert (
        q(session_factory, "SELECT COUNT(*) AS n FROM contacts WHERE name='+639171234567'")[0].n
        == 0
    )
