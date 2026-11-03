import json

import httpx
import pytest

from telegram_bot_gateway.adapters.outbound.inbox import HttpInbox, ServiceToken
from telegram_bot_gateway.application.ports import InboxError

# Covers: FR-INX-13, FR-INX-12, FR-INX-02, FR-INX-04, FR-INX-06, FR-INX-08

BASE = "http://inbox.test/api/v1"


class Server:
    def __init__(self, routes):
        self.routes, self.requests, self.token_calls = routes, [], 0

    def handler(self, request: httpx.Request) -> httpx.Response:
        if request.url.path == "/token":
            self.token_calls += 1
            return httpx.Response(200, json={"access_token": f"t{self.token_calls}", "expires_in": 300})
        self.requests.append((request.url.path, request.headers.get("authorization"), json.loads(request.content or b"{}")))
        answer = self.routes[request.url.path]
        if callable(answer):
            answer = answer(len(self.requests))
        return answer if isinstance(answer, httpx.Response) else httpx.Response(answer[0], json=answer[1])


def build(routes, **token):
    server = Server(routes)
    client = httpx.AsyncClient(transport=httpx.MockTransport(server.handler))
    clock = token.pop("clock", None) or (lambda: 0.0)
    service = ServiceToken(client=client, clock=clock, **token)
    return server, HttpInbox(BASE, service, client), service


async def test_lease_posts_limit_and_seconds_with_the_static_service_bearer():
    server, inbox, _ = build({"/api/v1/outbox/lease": (200, {"items": [{"id": "1"}]})}, static="svc")
    assert await inbox.lease(7, 90) == [{"id": "1"}]
    assert server.requests == [("/api/v1/outbox/lease", "Bearer svc", {"limit": 7, "lease_seconds": 90})]


async def test_a_client_credentials_token_is_cached_and_fetched_again_near_expiry():
    now = [0.0]
    server, inbox, _ = build(
        {"/api/v1/outbox/lease": (200, {"items": []})}, token_url="http://inbox.test/token",
        client_id="c", client_secret="s", clock=lambda: now[0],
    )
    await inbox.lease(1, 1)
    await inbox.lease(1, 1)
    assert server.token_calls == 1 and server.requests[1][1] == "Bearer t1"
    now[0] = 250.0
    await inbox.lease(1, 1)
    assert server.token_calls == 2 and server.requests[2][1] == "Bearer t2"


async def test_a_refused_token_is_dropped_and_the_call_repeated_once():
    server, inbox, _ = build(
        {"/api/v1/outbox/lease": lambda n: (401, {}) if n == 1 else (200, {"items": []})},
        token_url="http://inbox.test/token", client_id="c", client_secret="s",
    )
    assert await inbox.lease(1, 1) == []
    assert server.token_calls == 2 and [r[1] for r in server.requests] == ["Bearer t1", "Bearer t2"]


async def test_ack_and_release_carry_the_reference_and_the_delay():
    server, inbox, _ = build({"/api/v1/outbox/i1/ack": (200, {"ok": True}), "/api/v1/outbox/i2/release": (200, {"ok": True})}, static="s")
    await inbox.ack("i1", "5:100")
    await inbox.release("i2", 30, "boom")
    assert server.requests[0][2] == {"external_ref": "5:100"} and server.requests[1][2] == {"retry_in": 30, "error": "boom"}


async def test_a_service_that_fails_raises_inbox_error():
    _, inbox, _ = build({"/api/v1/outbox/lease": (500, {})}, static="s")
    with pytest.raises(InboxError):
        await inbox.lease(1, 1)


async def test_a_press_uses_the_pressing_persons_bearer_and_maps_the_answers():
    cases = [
        (200, {"approval": {}}, "decided"), (403, {}, "forbidden"), (404, {}, "gone"), (401, {}, "unauthorized"),
        (409, {"error": {"code": "already_decided"}}, "already_decided"), (409, {"error": {"code": "other"}}, "failed"),
        (500, {}, "failed"),
    ]
    for status, body, outcome in cases:
        server, inbox, _ = build({"/api/v1/buttons/press": (status, body)}, static="service-token")
        assert (await inbox.press("person-token", "b1")).outcome == outcome
        assert server.requests == [("/api/v1/buttons/press", "Bearer person-token", {"button": "b1"})]


async def test_a_reply_is_sent_under_the_persons_bearer_and_errors_carry_the_services_message():
    server, inbox, _ = build({"/api/v1/replies": (200, {"kind": "answer"})}, static="svc")
    assert (await inbox.reply("person", "ask:1", "yes")).ok
    assert server.requests == [("/api/v1/replies", "Bearer person", {"ref": "ask:1", "text": "yes"})]
    _, inbox, _ = build({"/api/v1/replies": (409, {"error": {"message": "Conversation closed."}})}, static="s")
    result = await inbox.reply("p", "r", "t")
    assert not result.ok and result.message == "Conversation closed."
    _, inbox, _ = build({"/api/v1/replies": (500, {})}, static="s")
    assert (await inbox.reply("p", "r", "t")) == type(result)(False, "")


async def test_link_reports_whether_the_code_was_accepted():
    server, inbox, _ = build({"/api/v1/outbox/link": (200, {"channel": {}})}, static="s")
    assert await inbox.link("CODE", "55", "ann") is True
    assert server.requests[0][2] == {"code": "CODE", "address": "55", "label": "ann"}
    _, inbox, _ = build({"/api/v1/outbox/link": (404, {})}, static="s")
    assert await inbox.link("BAD", "55", "ann") is False
    _, inbox, _ = build({"/api/v1/outbox/link": (500, {})}, static="s")
    with pytest.raises(InboxError):
        await inbox.link("X", "55", "ann")


async def test_a_press_may_be_answered_with_a_reply_prompt_and_a_broken_one_is_ignored():
    prompt = {"ref": "ask:7", "text": "Type your answer."}
    _, inbox, _ = build({"/api/v1/buttons/press": (200, {"approval": {}, "reply_prompt": prompt})}, static="s")
    press = await inbox.press("p", "qa:7:other")
    assert press.outcome == "decided" and (press.prompt.ref, press.prompt.text) == ("ask:7", "Type your answer.")
    for body in ({"approval": {}}, {"reply_prompt": {"ref": "x"}}, {"reply_prompt": "no"}, {"reply_prompt": {"ref": "", "text": "t"}}):
        _, inbox, _ = build({"/api/v1/buttons/press": (200, body)}, static="s")
        assert (await inbox.press("p", "b")).prompt is None
