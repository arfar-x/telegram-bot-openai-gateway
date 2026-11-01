from telegram_bot_gateway.application import inbox as delivery
from telegram_bot_gateway.application.ports import DeliveryFailed, InboxError, Press
from telegram_bot_gateway.domain import inbox as model
from tests.fakes import FakeStore

# Covers: FR-INX-03, FR-INX-04, FR-INX-05, FR-INX-09


class FakeInbox:
    def __init__(self):
        self.acks, self.releases = [], []
        self.ack_fails = False

    async def ack(self, item_id, external_ref):
        if self.ack_fails:
            raise InboxError("down")
        self.acks.append((item_id, external_ref))

    async def release(self, item_id, retry_in, error):
        self.releases.append((item_id, retry_in, error))


class FakeMessenger:
    def __init__(self):
        self.calls, self.fail, self._ids = [], None, iter(range(100, 200))

    async def send_text(self, chat_id, text):
        return self._send("text", chat_id, text)

    async def send_buttons(self, chat_id, text, buttons):
        return self._send("buttons", chat_id, text, buttons)

    def _send(self, *call):
        if self.fail:
            raise self.fail
        self.calls.append(call)
        return model.format_ref(call[1], next(self._ids))

    async def replace(self, chat_id, message_id, text):
        if self.fail:
            raise self.fail
        self.calls.append(("replace", chat_id, message_id, text))


def item(id="i1", kind="text", body="hello", address="55", buttons=(), ref=""):
    return {"id": id, "kind": kind, "body": body, "external_ref": ref, "buttons": list(buttons), "channel": {"address": address}}


async def run(raw, inbox=None, store=None, messenger=None):
    inbox, store, messenger = inbox or FakeInbox(), store or FakeStore(), messenger or FakeMessenger()
    await delivery.deliver(raw, inbox=inbox, store=store, messenger=messenger)
    return inbox, store, messenger


async def test_a_text_item_is_sent_then_acknowledged_with_its_chat_and_message_id():
    inbox, store, messenger = await run(item())
    assert messenger.calls == [("text", 55, "hello")]
    assert inbox.acks == [("i1", "55:100")] and store.deliveries == {"i1": "55:100"}


async def test_an_approval_becomes_one_message_with_a_button_per_entry():
    buttons = [{"id": "b-yes", "label": "Approve", "style": "primary"}, {"id": "b-no", "label": "Reject"}]
    inbox, _, messenger = await run(item(kind="approval", body="Run it?", buttons=buttons))
    assert messenger.calls == [("buttons", 55, "Run it?", [("Approve", "i:b-yes"), ("Reject", "i:b-no")])]
    assert inbox.acks == [("i1", "55:100")]


async def test_two_approvals_in_one_chat_are_two_messages_that_do_not_share_state():
    messenger = FakeMessenger()
    a = [{"id": "a-yes", "label": "Approve"}]
    b = [{"id": "b-yes", "label": "Approve"}]
    inbox, store, _ = await run(item("a", "approval", "A?", buttons=a), messenger=messenger)
    await run(item("b", "approval", "B?", buttons=b), inbox, store, messenger)
    assert [c[3] for c in messenger.calls] == [[("Approve", "i:a-yes")], [("Approve", "i:b-yes")]]
    assert inbox.acks == [("a", "55:100"), ("b", "55:101")]


async def test_an_update_replaces_the_named_message_and_acknowledges_its_reference():
    inbox, _, messenger = await run(item(kind="update", body="Approved by Ann", ref="-100123:42"))
    assert messenger.calls == [("replace", -100123, 42, "Approved by Ann")]
    assert inbox.acks == [("i1", "-100123:42")]


async def test_a_failed_send_is_released_with_the_delay_it_carries_and_not_remembered():
    messenger = FakeMessenger()
    messenger.fail = DeliveryFailed("Telegram asked to slow down", 17)
    inbox, store, _ = await run(item(), messenger=messenger)
    assert inbox.releases == [("i1", 17, "Telegram asked to slow down")] and inbox.acks == [] and store.deliveries == {}


async def test_an_item_offered_again_is_acknowledged_and_not_sent_twice():
    inbox, store, messenger = await run(item())
    await run(item(), inbox, store, messenger)
    assert len(messenger.calls) == 1 and inbox.acks == [("i1", "55:100"), ("i1", "55:100")]


async def test_an_ack_that_fails_leaves_the_delivery_remembered_so_the_retry_sends_nothing():
    inbox = FakeInbox()
    inbox.ack_fails = True
    _, store, messenger = await run(item(), inbox)
    inbox.ack_fails = False
    await run(item(), inbox, store, messenger)
    assert len(messenger.calls) == 1 and inbox.acks == [("i1", "55:100")]


async def test_an_item_that_cannot_be_addressed_is_released_not_dropped():
    inbox, _, messenger = await run(item(address="not-a-chat"))
    assert messenger.calls == [] and inbox.releases[0][0] == "i1"
    inbox, _, _ = await run(item("u", "update", ref="garbage"))
    assert inbox.releases[0][0] == "u"
    long_id = "x" * 70
    inbox, _, _ = await run(item("t", "approval", buttons=[{"id": long_id, "label": "L"}]))
    assert inbox.releases[0][0] == "t"


async def test_an_unreadable_item_is_ignored():
    inbox, store, messenger = await run({"kind": "mystery"})
    assert messenger.calls == [] and inbox.acks == [] and inbox.releases == []


def test_refs_round_trip_including_negative_group_ids():
    assert model.parse_ref(model.format_ref(-1001, 7)) == (-1001, 7)
    assert model.parse_ref("nope") is None and isinstance(Press("decided"), Press)
