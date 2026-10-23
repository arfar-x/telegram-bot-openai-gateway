import pytest
from telegram.error import BadRequest, Forbidden, NetworkError

from telegram_bot_gateway.adapters.inbound.telegram.actions import UNREACHABLE, TelegramActions
from telegram_bot_gateway.adapters.inbound.telegram.sender import Sender, Target
from telegram_bot_gateway.application.ports import ActionError
from telegram_bot_gateway.domain.tools import buttons, files, images
from tests.fakes import FakeBot, FakeStore

# Covers: FR-TLS-02, FR-TLS-03, FR-TLS-04, FR-TLS-05, FR-TLS-06, FR-TLS-07, FR-TLS-08


def make(target=None, on_react=None):
    bot = FakeBot()
    target = target or Target(5, "private", None, 10, "fa")
    return bot, TelegramActions(bot, Sender(bot, FakeStore()), target, on_react=on_react)


async def test_a_file_goes_to_the_chat_of_the_turn_as_a_document():
    bot, actions = make(Target(-100, "supergroup", 33, 10))
    await actions.send_file(files.File("r.md", b"# R", "cap"))
    sent, = bot.documents
    assert sent["chat_id"] == -100 and sent["message_thread_id"] == 33 and sent["caption"] == "cap"
    assert sent["document"].filename == "r.md"


async def test_an_image_url_is_handed_to_telegram_and_data_is_uploaded():
    bot, actions = make()
    await actions.send_image(images.Image("https://x.io/a.png", None, None))
    await actions.send_image(images.Image(None, b"\x89PNG", "c"))
    assert bot.photos[0]["photo"] == "https://x.io/a.png"
    assert bot.photos[1]["photo"].filename == "image" and bot.photos[1]["caption"] == "c"


async def test_buttons_are_links_or_copy_buttons_one_per_row():
    bot, actions = make()
    await actions.send_buttons(buttons.Buttons("Pick", (buttons.Button("Docs", url="https://d.io"), buttons.Button("Copy", copy="ls"))))
    rows = bot.sent[0]["reply_markup"].inline_keyboard
    assert [len(r) for r in rows] == [1, 1]
    assert rows[0][0].url == "https://d.io" and rows[1][0].copy_text.text == "ls"
    assert not bot.sent[0]["disable_notification"]


async def test_a_note_is_silent_and_not_a_reply():
    bot, actions = make()
    await actions.notify("searching")
    assert bot.sent[0]["disable_notification"] is True and "reply_parameters" not in bot.sent[0]


async def test_a_reaction_is_set_on_the_users_message_and_reported():
    seen = []
    bot, actions = make(on_react=lambda: seen.append(1))
    await actions.react("👍")
    assert bot.reactions == [(10, ["👍"])] and seen == [1]


async def test_there_is_nothing_to_react_to_after_a_button_answer():
    _, actions = make(Target(5, "private", None, None))
    with pytest.raises(ActionError, match="no message to react to"):
        await actions.react("👍")


async def test_the_facts_are_the_chat_type_the_topic_and_the_language():
    _, actions = make(Target(-1, "supergroup", 7, 1, "fa"))
    facts = actions.facts()
    assert (facts.chat_type, facts.topic, facts.language) == ("supergroup", True, "fa")


async def test_a_refusal_by_telegram_is_an_action_error_with_its_reason():
    bot, actions = make()
    bot.fail_next = [BadRequest("wrong file type")]
    with pytest.raises(ActionError, match="wrong file type"):
        await actions.send_file(files.File("a.txt", b"x", None))
    bot.fail_next = [Forbidden("bot was blocked by the user")]
    with pytest.raises(ActionError, match="blocked"):
        await actions.send_image(images.Image("https://x.io/a.png", None, None))


async def test_a_network_failure_never_leaks_its_details():
    bot, actions = make()
    bot.fail_next = [NetworkError("httpx.ConnectError: https://api.telegram.org/bot123:SECRET/sendDocument")]
    with pytest.raises(ActionError) as caught:
        await actions.send_file(files.File("a.txt", b"x", None))
    assert str(caught.value) == UNREACHABLE and "SECRET" not in str(caught.value)


async def test_a_missing_topic_is_retried_without_it():
    bot, actions = make(Target(-1, "supergroup", 33, 1))
    bot.fail_next = [BadRequest("Message thread not found")]
    await actions.send_file(files.File("a.txt", b"x", None))
    assert "message_thread_id" not in bot.documents[0]
