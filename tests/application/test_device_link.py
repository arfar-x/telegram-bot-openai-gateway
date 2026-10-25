import asyncio

import pytest

from telegram_bot_gateway.application import linking
from telegram_bot_gateway.application.model import Link, Session
from telegram_bot_gateway.application.ports import IdentityRefused, IdentityUnavailable, Tokens
from tests.fakes import FakeIdentity, FakeStore, FakeVault, approved

# Covers: FR-LNK-12, FR-LNK-13, FR-LNK-14, FR-LNK-15, FR-LNK-16, FR-LNK-17, FR-LNK-10, FR-LNK-01, FR-LNK-06

NOW = 1_000_000.0


async def begin(store, identity, **kw):
    return await linking.start_login(
        store, FakeVault(), identity, telegram_user_id=5, chat_id=5, username="Ann", telegram_name="Ann Q", now=NOW, **kw
    )


async def signed_in(store=None, identity=None):
    store, identity = store or FakeStore(), identity or FakeIdentity(polls=[approved()])
    login = await begin(store, identity)
    progress = await linking.poll_login(store, FakeVault(), identity, login, now=NOW + 5)
    assert isinstance(progress, linking.SignedIn)
    return store, identity


class Clock:
    def __init__(self, now=NOW):
        self.now = now

    def __call__(self):
        return self.now


def bearer(store, identity, clock):
    return linking.Bearer(store, FakeVault(), identity, clock=clock, lock_factory=asyncio.Lock)


async def test_a_login_is_stored_with_the_device_code_encrypted_and_replaced_by_a_new_one():
    store, identity = FakeStore(), FakeIdentity()
    first = await begin(store, identity)
    assert first.device_code_enc != "dev-1" and first.expires_at == NOW + 600 and first.interval_seconds == 5
    second = await begin(store, identity)
    assert list(store.logins.values()) == [second] and second.device_code_enc != first.device_code_enc


async def test_pending_slow_down_and_then_approval():
    store, identity = FakeStore(), FakeIdentity(polls=["pending", "slow_down", "pending", approved()])
    login = await begin(store, identity)
    vault = FakeVault()
    assert await linking.poll_login(store, vault, identity, login, now=NOW + 5) == linking.Waiting(5)
    assert await linking.poll_login(store, vault, identity, login, now=NOW + 10) == linking.Waiting(10)
    assert store.logins[5].interval_seconds == 10  # the slower pace is kept
    assert await linking.poll_login(store, vault, identity, login, now=NOW + 20) == linking.Waiting(10)
    done = await linking.poll_login(store, vault, identity, login, now=NOW + 30)
    assert isinstance(done, linking.SignedIn) and store.logins == {}
    assert identity.polled == ["dev-1"] * 4  # the decrypted code, every time


async def test_approval_stores_the_refresh_token_encrypted_with_the_subject_and_no_access_token():
    store, _ = await signed_in()
    link = store.links[5]
    assert (link.kind, link.status, link.subject, link.username) == ("oidc", "active", "sub-1", "ann")
    assert link.refresh_token_enc == "enc:rt-1" and link.api_key_enc is None
    assert "at-0" not in repr(link)


async def test_the_display_name_falls_back_to_the_telegram_name():
    store, identity = FakeStore(), FakeIdentity(polls=[approved(username=None)])
    login = await begin(store, identity)
    await linking.poll_login(store, FakeVault(), identity, login, now=NOW + 5)
    assert store.links[5].username == "Ann Q"


@pytest.mark.parametrize("status,reason", [("denied", "denied"), ("expired", "expired")])
async def test_denial_and_issuer_expiry_end_the_login(status, reason):
    store, identity = FakeStore(), FakeIdentity(polls=[status])
    login = await begin(store, identity)
    assert await linking.poll_login(store, FakeVault(), identity, login, now=NOW + 5) == linking.Ended(reason)
    assert store.logins == {} and store.links == {}


async def test_the_codes_own_expiry_ends_the_login_without_asking_the_issuer():
    store, identity = FakeStore(), FakeIdentity()
    login = await begin(store, identity)
    assert await linking.poll_login(store, FakeVault(), identity, login, now=NOW + 601) == linking.Ended("expired")
    assert identity.polled == [] and store.logins == {}


async def test_a_transient_failure_while_waiting_is_retried_at_the_same_pace():
    store, identity = FakeStore(), FakeIdentity(polls=[IdentityUnavailable("down"), approved()])
    login = await begin(store, identity)
    assert await linking.poll_login(store, FakeVault(), identity, login, now=NOW + 5) == linking.Waiting(5)
    assert isinstance(await linking.poll_login(store, FakeVault(), identity, login, now=NOW + 10), linking.SignedIn)


@pytest.mark.parametrize("answer", [approved(subject=None), approved(refresh=None)])
async def test_an_approval_without_a_subject_or_a_refresh_token_fails_the_login(answer):
    store, identity = FakeStore(), FakeIdentity(polls=[answer])
    login = await begin(store, identity)
    assert await linking.poll_login(store, FakeVault(), identity, login, now=NOW + 5) == linking.Ended("incomplete")
    assert store.links == {} and store.logins == {}


async def test_a_replaced_login_is_not_polled_any_more():
    store, identity = FakeStore(), FakeIdentity()
    old = await begin(store, identity)
    store.logins[5] = type(old)(**{**old.__dict__, "user_code": "OTHER-CODE"})
    assert await linking.poll_login(store, FakeVault(), identity, old, now=NOW + 5) == linking.Ended("replaced")
    assert identity.polled == [] and 5 in store.logins


async def test_an_approved_login_replaces_a_pairing_link():
    store = FakeStore()
    await store.save_link(Link(5, "old", "Ann", "enc:key"))
    await store.save_session(Session("5", 5))
    await signed_in(store)
    link = store.links[5]
    assert link.kind == "oidc" and link.api_key_enc is None and "5" in store.sessions


async def test_the_bearer_of_a_pairing_link_is_the_stored_key_and_never_touches_the_issuer():
    store, identity = FakeStore(), FakeIdentity()
    await store.save_link(Link(5, "ann", "Ann", "enc:agw_key"))
    assert await bearer(store, identity, Clock()).for_user(5) == "agw_key"
    assert identity.refreshed == [] and await bearer(store, identity, Clock()).for_user(6) is None


async def test_a_fresh_access_token_is_fetched_once_and_reused_until_a_minute_before_it_ends():
    store, identity = await signed_in()
    clock = Clock(NOW + 10)
    b = bearer(store, identity, clock)
    assert await b.for_user(5) == "access-1"
    clock.now = NOW + 10 + 239  # 61 seconds left
    assert await b.for_user(5) == "access-1" and identity.refreshed == ["rt-1"]
    clock.now = NOW + 10 + 241  # 59 seconds left
    assert await b.for_user(5) == "access-2"


async def test_a_rotated_refresh_token_is_stored_before_the_access_token_is_used():
    store, identity = await signed_in(identity=FakeIdentity(polls=[approved()], refreshes=[Tokens("a1", 300, "rt-2")]))
    seen = {}
    real = store.update_oidc_tokens

    async def spy(uid, enc, *, refreshed_at):
        seen["stored_before_use"], seen["enc"] = True, enc
        return await real(uid, enc, refreshed_at=refreshed_at)

    store.update_oidc_tokens = spy
    assert await bearer(store, identity, Clock(NOW + 10)).for_user(5) == "a1"
    assert seen == {"stored_before_use": True, "enc": "enc:rt-2"} and store.links[5].refresh_token_enc == "enc:rt-2"
    assert store.links[5].refreshed_at == NOW + 10


async def test_a_refresh_token_the_issuer_did_not_rotate_is_kept():
    store, identity = await signed_in(identity=FakeIdentity(polls=[approved()], refreshes=[Tokens("a1", 300)]))
    await bearer(store, identity, Clock(NOW + 10)).for_user(5)
    assert store.links[5].refresh_token_enc == "enc:rt-1"


async def test_concurrent_turns_of_one_user_refresh_once():
    store, identity = await signed_in()
    gate = asyncio.Event()
    real = identity.refresh

    async def slow(token):
        await gate.wait()
        return await real(token)

    identity.refresh = slow
    b = bearer(store, identity, Clock(NOW + 10))
    tasks = [asyncio.create_task(b.for_user(5)) for _ in range(4)]
    await asyncio.sleep(0.05)
    gate.set()
    assert set(await asyncio.gather(*tasks)) == {"access-1"} and identity.refreshed == ["rt-1"]


async def test_a_refused_refresh_expires_the_link_and_clears_the_token():
    store, identity = await signed_in(identity=FakeIdentity(polls=[approved()], refreshes=[IdentityRefused()]))
    b = bearer(store, identity, Clock(NOW + 10))
    with pytest.raises(linking.LinkExpired):
        await b.for_user(5)
    link = store.links[5]
    assert link.status == "expired" and link.refresh_token_enc is None
    with pytest.raises(linking.LinkExpired):  # and it is not asked again
        await b.for_user(5)
    assert identity.refreshed == ["rt-1"]


async def test_a_transient_refresh_failure_leaves_the_link_alone():
    store, identity = await signed_in(identity=FakeIdentity(polls=[approved()], refreshes=[IdentityUnavailable("503")]))
    with pytest.raises(IdentityUnavailable):
        await bearer(store, identity, Clock(NOW + 10)).for_user(5)
    assert store.links[5].status == "active" and store.links[5].refresh_token_enc == "enc:rt-1"


async def test_an_unreadable_refresh_token_asks_for_renewal():
    store, identity = await signed_in()

    class Wrong(FakeVault):
        def decrypt(self, ciphertext):
            raise ValueError("cannot be decrypted")

    with pytest.raises(linking.KeyUnreadable):
        await linking.Bearer(store, Wrong(), identity, clock=Clock(NOW + 10)).for_user(5)


async def test_a_link_removed_meanwhile_stops_the_held_token():
    store, identity = await signed_in()
    b = bearer(store, identity, Clock(NOW + 10))
    await b.for_user(5)
    await store.delete_links(telegram_user_id=5)
    assert await b.for_user(5) is None


async def test_logout_revokes_at_the_issuer_then_deletes_the_link_and_sessions():
    store, identity = await signed_in()
    await store.save_session(Session("5", 5))
    await store.save_device_login(await begin(store, identity))
    result = await linking.logout(store, FakeVault(), identity, 5)
    assert result == linking.LoggedOut(True, "revoked") and identity.revoked == ["rt-1"]
    assert store.links == {} and store.sessions == {} and store.logins == {}


@pytest.mark.parametrize("revoke,expected", [(False, "unsupported"), (IdentityUnavailable("x"), "failed")])
async def test_logout_deletes_the_link_whether_or_not_revocation_worked(revoke, expected):
    store, identity = await signed_in(identity=FakeIdentity(polls=[approved()], revokes=[revoke]))
    assert (await linking.logout(store, FakeVault(), identity, 5)).revocation == expected
    assert store.links == {}


async def test_logout_without_a_link_or_of_a_pairing_link():
    store = FakeStore()
    assert await linking.logout(store, FakeVault(), FakeIdentity(), 5) == linking.LoggedOut(False, "none")
    await store.save_link(Link(5, "ann", "Ann", "enc:k"))
    identity = FakeIdentity()
    assert await linking.logout(store, FakeVault(), identity, 5) == linking.LoggedOut(True, "none")
    assert identity.revoked == [] and store.links == {}


async def test_unlinking_removes_either_kind_and_a_pending_login():
    store, identity = await signed_in()
    await store.save_link(Link(6, "bob", "Bob", "enc:k"))
    await store.save_device_login(await begin(store, identity))
    assert await linking.unlink(store, username="ann") == 1
    assert await linking.unlink(store, telegram_user_id=6) == 1 and store.links == {} and store.logins == {}
