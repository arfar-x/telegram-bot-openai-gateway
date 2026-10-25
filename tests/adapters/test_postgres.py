import os
from pathlib import Path

import pytest

from telegram_bot_gateway.adapters.outbound.postgres import PostgresStore
from telegram_bot_gateway.application.model import DeviceLogin, Link, PairingRequest, Pending, Session

# Covers: FR-OPS-04, FR-SES-02, FR-SES-04, FR-SES-05, FR-ASK-07, FR-LNK-05, FR-LNK-12, FR-LNK-13, FR-LNK-15

pytestmark = pytest.mark.services
URL = os.environ.get("BOT_TEST_DATABASE_URL", "")
MIGRATIONS = Path(__file__).resolve().parents[2] / "migrations"


@pytest.fixture
async def store():
    if not URL:
        pytest.skip("BOT_TEST_DATABASE_URL not set (scripts/test-services.sh)")
    s = await PostgresStore.open(URL, MIGRATIONS)
    for table in ("links", "pairing_codes", "sessions", "message_texts", "device_logins"):
        await s._run(f"DELETE FROM {table}")
    yield s
    await s.close()


async def test_migrations_apply_once_and_reopening_is_harmless(store):
    again = await PostgresStore.open(URL, MIGRATIONS)
    names = [r["name"] for r in await again._rows("SELECT name FROM schema_migrations")]
    assert names == ["001_init.sql", "002_oidc_links.sql"]
    await again.close()


async def test_sessions_round_trip_exactly_including_tool_calls_and_pending(store):
    call = {"id": "c1", "type": "function", "function": {"name": "clarify", "arguments": '{"a": 1}'}}
    session = Session("-100:3:7", 7, "agent", {"temperature": 0.2},
                      [{"role": "user", "content": "hi"}, {"role": "assistant", "content": None, "tool_calls": [call]}],
                      Pending("c1", "Which?", ["a", "b"], -100, 12.5, 77))
    await store.save_session(session)
    assert await store.load_session("-100:3:7") == session
    found = await store.find_pending(-100, 77)
    assert found is not None and found.key == "-100:3:7"
    assert await store.find_pending(-100, 78) is None
    session.pending = None
    await store.save_session(session)
    assert (await store.load_session("-100:3:7")).pending is None and await store.find_pending(-100, 77) is None
    await store.delete_session("-100:3:7")
    assert await store.load_session("-100:3:7") is None


async def test_links_are_stored_encrypted_text_and_removed_by_id_or_username(store):
    await store.save_link(Link(5, "ann", "Ann", "gAAAA-ciphertext"))
    await store.save_link(Link(5, "ann2", "Ann", "gAAAA-new"))  # re-linking replaces
    assert (await store.get_link(5)).api_key_enc == "gAAAA-new"
    await store.save_link(Link(6, "bob", "Bob", "x"))
    assert [l.username for l in await store.list_links()] == ["ann2", "bob"]
    assert await store.delete_links(username="bob") == 1 and await store.delete_links(telegram_user_id=5) == 1


async def test_sessions_of_a_user_are_deleted_together(store):
    for key, uid in (("5", 5), ("-1:5", 5), ("6", 6)):
        await store.save_session(Session(key, uid))
    await store.delete_sessions_of(5)
    assert await store.load_session("5") is None and await store.load_session("6") is not None


async def test_pairing_codes_and_message_texts(store):
    req = PairingRequest("ABCD2345", 5, "ann", "Ann", 55, 100.0)
    await store.create_pairing(req)
    assert await store.get_pairing("ABCD2345") == req
    assert await store.pairings_of(5) == [req] and await store.list_pairings(since=50) == [req]
    assert await store.list_pairings(since=200) == []
    await store.delete_pairing("ABCD2345")
    assert await store.get_pairing("ABCD2345") is None
    await store.save_text(1, 2, "hello")
    await store.save_text(1, 2, "hello again")
    assert await store.get_text(1, 2) == "hello again" and await store.get_text(1, 3) is None


async def test_old_message_texts_and_expired_codes_can_be_pruned(store):
    await store.save_text(1, 1, "old")
    await store.save_text(1, 2, "new")
    await store._run("UPDATE message_texts SET created_at = now() - interval '40 days' WHERE message_id = 1")
    assert await store.prune_texts(older_than_days=30) == 1
    assert await store.get_text(1, 1) is None and await store.get_text(1, 2) == "new"
    await store.create_pairing(PairingRequest("OLD00000", 5, "a", "A", 5, 10.0))
    await store.create_pairing(PairingRequest("NEW00000", 5, "a", "A", 5, 5000.0))
    assert await store.prune_pairings(before=1000.0) == 1
    assert await store.get_pairing("OLD00000") is None and await store.get_pairing("NEW00000") is not None


async def test_oidc_links_round_trip_rotate_expire_and_replace_a_pairing_link(store):
    await store.save_link(Link(5, "ann", "Ann", "gAAAA-key"))
    old = await store.get_link(5)
    assert (old.kind, old.status, old.subject, old.refresh_token_enc, old.refreshed_at) == ("api_key", "active", None, None, None)
    oidc = Link(5, "ann", "Ann", kind="oidc", subject="sub-1", refresh_token_enc="gAAAA-rt1", refreshed_at=1_700_000_000.0)
    await store.save_link(oidc)  # replaces the pairing link, key gone
    assert await store.get_link(5) == oidc
    assert await store.update_oidc_tokens(5, "gAAAA-rt2", refreshed_at=1_700_000_100.0)
    assert (await store.get_link(5)).refresh_token_enc == "gAAAA-rt2" and (await store.get_link(5)).refreshed_at == 1_700_000_100.0
    assert await store.expire_link(5)
    expired = await store.get_link(5)
    assert (expired.status, expired.refresh_token_enc, expired.usable) == ("expired", None, False)
    assert not await store.update_oidc_tokens(5, "x", refreshed_at=1.0)  # an expired link takes no new token
    assert not await store.expire_link(99)
    await store.save_link(Link(6, "bob", "Bob", kind="oidc", subject="sub-1", refresh_token_enc="r"))  # one person, two accounts
    assert len(await store.list_links()) == 2


async def test_a_link_must_have_the_shape_of_its_kind(store):
    import psycopg

    for bad in (Link(7, "x", "X", kind="oidc"), Link(7, "x", "X", "k", subject="s"), Link(7, "x", "X", kind="oidc", subject="s", api_key_enc="k")):
        with pytest.raises(psycopg.errors.CheckViolation):
            await store.save_link(bad)


async def test_device_logins_are_one_per_user_replaced_pruned_and_deleted_by_code(store):
    login = DeviceLogin(5, 55, "ann", "Ann", "gAAAA-dev", "WDJB-MJHT", "https://i/d", "https://i/d?c=1", 5, 2_000_000_000.5)
    await store.save_device_login(login)
    assert await store.get_device_login(5) == login
    newer = DeviceLogin(5, 55, "ann", "Ann", "gAAAA-dev2", "NEWCODE", "https://i/d", None, 10, 2_000_000_100.0)
    await store.save_device_login(newer)  # replaces
    assert await store.list_device_logins() == [newer]
    await store.delete_device_login(5, user_code="WDJB-MJHT")  # a stale poller cannot delete its replacement
    assert await store.get_device_login(5) == newer
    assert await store.prune_device_logins(before=2_000_000_050.0) == 0 and await store.prune_device_logins(before=2_000_000_200.0) == 1
    await store.save_device_login(login)
    await store.delete_device_login(5)
    assert await store.get_device_login(5) is None
