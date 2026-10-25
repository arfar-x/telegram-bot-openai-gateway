import logging

import httpx
import pytest

from telegram_bot_gateway.adapters.outbound.oidc import DISCOVERY_TTL_SECONDS, IssuerMisconfigured, OidcIdentity, claims_of
from telegram_bot_gateway.application.ports import IdentityRefused, IdentityUnavailable
from tests.adapters.fake_issuer import BASE, FakeIssuer, jwt

# Covers: FR-LNK-11, FR-LNK-12, FR-LNK-13, FR-LNK-15, FR-LNK-16, FR-LNK-18, FR-CFG-05


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


def identity(issuer, **kw):
    return OidcIdentity(BASE + "/", "bot-client", client=issuer.client(), **kw)


async def test_endpoints_come_from_the_discovery_document_which_is_cached_for_an_hour():
    issuer, clock = FakeIssuer(), Clock()
    idp = identity(issuer, clock=clock)
    await idp.start_device()
    await idp.start_device()
    assert issuer.discovery_hits == 1
    clock.now = DISCOVERY_TTL_SECONDS + 1
    await idp.start_device()
    assert issuer.discovery_hits == 2
    assert [p for p, _ in issuer.requests if p == "/device"] and issuer.requests[0][0] == "/.well-known/openid-configuration"


async def test_the_device_authorization_asks_for_the_configured_scope_and_returns_what_the_user_needs():
    issuer = FakeIssuer(interval=7, expires_in=300)
    auth = await identity(issuer, scope="openid offline_access extra").start_device()
    assert (auth.user_code, auth.interval, auth.expires_in) == ("WDJB-MJHT", 7, 300)
    assert auth.verification_uri.endswith("/device") and auth.verification_uri_complete.endswith("user_code=WDJB-MJHT")
    path, form = [r for r in issuer.requests if r[0] == "/device"][0]
    assert form == {"client_id": "bot-client", "scope": "openid offline_access extra"}


async def test_a_confidential_client_authenticates_and_a_public_one_does_not():
    issuer = FakeIssuer()
    await identity(issuer, client_secret="s3cret").start_device()
    assert [h for h in issuer.auth_headers[1:] if h][0].startswith("Basic ")
    public = FakeIssuer()
    await identity(public).start_device()
    assert not any(public.auth_headers)


async def test_polling_maps_every_answer_of_the_token_endpoint():
    issuer = FakeIssuer()
    idp = identity(issuer)
    assert (await idp.poll("d")).status == "pending"
    issuer.slow_down_next = 1
    assert (await idp.poll("d")).status == "slow_down"
    issuer.denied = True
    assert (await idp.poll("d")).status == "denied"
    issuer.denied, issuer.expired_code = False, True
    assert (await idp.poll("d")).status == "expired"
    issuer.expired_code, issuer.approved = False, True
    done = await idp.poll("d")
    assert done.status == "approved" and done.tokens.subject == "sub-ann" and done.tokens.username == "ann"
    assert done.tokens.refresh_token and done.tokens.access_token and done.tokens.expires_in == 300


async def test_the_subject_comes_from_userinfo_when_the_token_response_has_no_id_token():
    issuer = FakeIssuer()
    issuer.approved = True
    real = issuer.handle

    def without_id_token(request):
        reply = real(request)
        if request.url.path.endswith("/token"):
            import json
            body = json.loads(reply.content)
            body.pop("id_token", None)
            return httpx.Response(200, json=body)
        return reply

    idp = OidcIdentity(BASE, "c", client=httpx.AsyncClient(transport=httpx.MockTransport(without_id_token)))
    assert (await idp.poll("d")).tokens.subject == "sub-ann"


async def test_claims_are_read_without_a_signature_and_garbage_gives_none():
    assert claims_of(jwt({"sub": "s"})) == {"sub": "s"}
    assert claims_of("nonsense") == {} and claims_of(None) == {} and claims_of("a.!!!.c") == {}


async def test_an_unexpected_poll_answer_or_a_5xx_is_transient():
    issuer = FakeIssuer()
    idp = identity(issuer)
    await idp.poll("d")
    issuer.down = True
    with pytest.raises(IdentityUnavailable):
        await idp.poll("d")


async def test_refresh_returns_new_tokens_and_a_rotated_refresh_token():
    issuer = FakeIssuer()
    issuer.approved = True
    idp = identity(issuer)
    first = (await idp.poll("d")).tokens
    again = await idp.refresh(first.refresh_token)
    assert again.access_token != first.access_token and again.refresh_token != first.refresh_token
    with pytest.raises(IdentityRefused):  # the old one was rotated away
        await idp.refresh(first.refresh_token)


async def test_a_disabled_account_is_a_refusal_and_an_outage_is_not():
    issuer = FakeIssuer()
    issuer.approved = True
    idp = identity(issuer)
    token = (await idp.poll("d")).tokens.refresh_token
    issuer.disabled = True
    with pytest.raises(IdentityRefused):
        await idp.refresh(token)
    issuer.down = True
    with pytest.raises(IdentityUnavailable):
        await idp.refresh(token)
    unreachable = OidcIdentity(BASE, "c", client=httpx.AsyncClient(transport=httpx.MockTransport(lambda r: (_ for _ in ()).throw(httpx.ConnectError("no")))))
    with pytest.raises(IdentityUnavailable):
        await unreachable.refresh(token)


async def test_revocation_uses_the_advertised_endpoint_and_reports_when_there_is_none():
    issuer = FakeIssuer()
    assert await identity(issuer).revoke("rt") is True and issuer.revoked == ["rt"]
    path, form = [r for r in issuer.requests if r[0] == "/revoke"][0]
    assert form["token_type_hint"] == "refresh_token"
    assert await identity(FakeIssuer(revocation=False)).revoke("rt") is False
    broken = FakeIssuer()
    idp = identity(broken)
    await idp.discovery()
    broken.down = True
    with pytest.raises(IdentityUnavailable):
        await idp.revoke("rt")


async def test_start_fails_the_configuration_when_the_issuer_has_no_device_endpoint():
    with pytest.raises(IssuerMisconfigured):
        await identity(FakeIssuer(device=False)).ensure_device_flow()
    await identity(FakeIssuer()).ensure_device_flow()
    down = FakeIssuer()
    down.down = True
    with pytest.raises(IdentityUnavailable):  # the caller warns and starts anyway
        await identity(down).ensure_device_flow()


async def test_no_token_or_device_code_reaches_a_log_or_an_error(caplog):
    issuer = FakeIssuer()
    issuer.approved = True
    idp = identity(issuer, client_secret="s3cret")
    with caplog.at_level(logging.DEBUG):
        tokens = (await idp.poll("DEVICE-SECRET")).tokens
        issuer.disabled = True
        with pytest.raises(IdentityRefused) as refused:
            await idp.refresh(tokens.refresh_token)
        issuer.down = True
        with pytest.raises(IdentityUnavailable) as down:
            await idp.refresh(tokens.refresh_token)
    secrets = [tokens.refresh_token, tokens.access_token, "DEVICE-SECRET", "s3cret"]
    for text in (caplog.text, str(refused.value), str(down.value), repr(refused.value), repr(down.value)):
        assert not any(s in text for s in secrets)
