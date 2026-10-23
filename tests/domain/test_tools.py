import base64
import json
from datetime import datetime, timezone

import pytest

from telegram_bot_gateway.domain import tools
from telegram_bot_gateway.domain.tools import approval, buttons, context, files, images, notify, reaction
from telegram_bot_gateway.domain.tools.base import ToolError

# Covers: FR-TLS-01, FR-TLS-03, FR-TLS-04, FR-TLS-05, FR-TLS-06, FR-TLS-07, FR-TLS-08, FR-TLS-09


def test_every_tool_is_declared_in_order_and_only_the_enabled_ones():
    assert [t["function"]["name"] for t in tools.declarations(tools.ALL)] == [
        "request_approval", "send_file", "send_image", "send_buttons", "notify", "react", "get_context",
    ]
    assert [t["function"]["name"] for t in tools.declarations(["notify", "send_file"])] == ["send_file", "notify"]
    assert tools.declarations([]) == []


def test_the_tools_variable_means_all_none_or_a_list():
    assert tools.parse_names("") == tools.ALL
    assert tools.parse_names("none") == ()
    assert tools.parse_names(" notify , send_file ") == ("send_file", "notify")
    with pytest.raises(ValueError, match="shell"):
        tools.parse_names("notify,shell")


@pytest.mark.parametrize("raw, name", [
    ("report.md", "report.md"), ("../../etc/passwd", "passwd.txt"), ("a\\b\\c.csv", "c.csv"),
    (".hidden", "hidden.txt"), ("", "file.txt"), ("x" * 300 + ".md", ("x" * 100)),
])
def test_a_file_name_is_reduced_to_a_safe_last_part(raw, name):
    cleaned = files.clean_name(raw)
    assert cleaned.startswith(name[:50]) and "/" not in cleaned and "\\" not in cleaned and len(cleaned) <= 104
    if len(name) < 50:
        assert cleaned == name


def test_a_file_carries_its_text_as_utf8_and_a_caption():
    f = files.parse(json.dumps({"filename": "a.txt", "content": "héllo", "caption": "c"}), max_bytes=100)
    assert (f.name, f.data, f.caption) == ("a.txt", "héllo".encode(), "c")


@pytest.mark.parametrize("args", [
    "not json", "[]", '{"filename":"a","content":""}', '{"content":"x"}', '{"filename":"a","content":"x"}'.replace('"x"', "5"),
    json.dumps({"filename": "a.txt", "content": "x" * 101}),
])
def test_a_bad_file_is_refused_with_a_reason(args):
    with pytest.raises(ToolError):
        files.parse(args, max_bytes=100)


def test_an_image_takes_exactly_one_source():
    assert images.parse('{"url":"https://x.io/a.png"}').url == "https://x.io/a.png"
    png = base64.b64encode(b"\x89PNG data").decode()
    assert images.parse(json.dumps({"base64": png, "caption": "c"})).data == b"\x89PNG data"
    assert images.parse(json.dumps({"base64": "data:image/png;base64," + png})).data == b"\x89PNG data"
    for bad in ('{}', json.dumps({"url": "https://x.io", "base64": png}), '{"url":"file:///etc/passwd"}',
                '{"url":"ftp://x/a.png"}', '{"base64":"***"}'):
        with pytest.raises(ToolError):
            images.parse(bad)


def test_buttons_open_links_or_copy_texts_one_per_row():
    b = buttons.parse(json.dumps({"text": "Pick", "buttons": [{"label": "Docs", "url": "https://d.io"}, {"label": "Copy", "copy": "ls -l"}]}))
    assert b.text == "Pick" and b.buttons == (buttons.Button("Docs", url="https://d.io"), buttons.Button("Copy", copy="ls -l"))


@pytest.mark.parametrize("button", [
    {"label": "x"}, {"label": "x", "url": "https://a.io", "copy": "c"}, {"label": "x", "url": "javascript:alert(1)"},
    {"label": "x", "url": "tg://resolve?domain=a"}, {"label": "y" * 65, "copy": "c"}, {"label": "x", "copy": "c" * 257}, "x",
])
def test_a_bad_button_is_refused(button):
    with pytest.raises(ToolError):
        buttons.parse(json.dumps({"text": "t", "buttons": [button]}))


def test_the_number_of_buttons_is_limited():
    ok = {"label": "x", "copy": "c"}
    buttons.parse(json.dumps({"text": "t", "buttons": [ok] * 8}))
    for n in (0, 9):
        with pytest.raises(ToolError):
            buttons.parse(json.dumps({"text": "t", "buttons": [ok] * n}))


def test_a_note_needs_text():
    assert notify.parse('{"text":"searching"}') == "searching"
    with pytest.raises(ToolError):
        notify.parse("{}")


def test_only_emoji_telegram_allows_are_reactions():
    assert reaction.parse('{"emoji":"👍"}') == "👍"
    assert reaction.parse('{"emoji":"❤️"}') == "❤"  # the variation selector is dropped
    assert reaction.parse('{"emoji":"❤️‍🔥"}') == "❤‍🔥"
    with pytest.raises(ToolError):
        reaction.parse('{"emoji":"🦖"}')


def test_the_context_has_four_facts_and_nothing_that_names_the_user():
    out = json.loads(context.render(chat_type="supergroup", topic=True, language=None, now=datetime(2026, 10, 23, 10, tzinfo=timezone.utc)))
    assert out == {"chat_type": "supergroup", "topic": True, "language": None, "utc_now": "2026-10-23T10:00:00Z"}


def test_an_approval_has_the_action_in_bold_the_effect_and_two_choices_without_other():
    q = approval.parse('{"action":"Delete DATA-1","effect":"It cannot be undone."}')
    assert q.text == "**Delete DATA-1**\nIt cannot be undone." and q.options == ("Allow", "Reject")
    assert q.show_other is False
    assert approval.parse('{"action":"Go"}').text == "**Go**"
    with pytest.raises(ToolError):
        approval.parse("{}")
