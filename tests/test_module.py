"""The repository stands on its own, and its start-up behaves."""

import asyncio
import logging
import re
from pathlib import Path
from types import SimpleNamespace

from telegram.error import Conflict
from telegram.ext import Application

from telegram_bot_gateway.adapters.inbound.telegram import bot as handlers
from telegram_bot_gateway.adapters.inbound.telegram import serve as serve_mod
from telegram_bot_gateway.config import Settings

# Covers: NFR-ARC-02, NFR-ARC-03, NFR-ARC-04, FR-LNK-08, FR-LNK-09, FR-CFG-02, FR-OPS-02, FR-OPS-05, FR-OPS-07

MODULE = Path(__file__).resolve().parent.parent
TRACKED_TEXT = [p for p in MODULE.rglob("*")
                if p.is_file() and p.suffix in {".py", ".md", ".yaml", ".yml", ".sh", ".mk", ".sql", ".toml", ".example"} or p.name in {"Makefile", "Dockerfile", ".gitignore", ".dockerignore"}]
SKIPPED_DIRS = {".venv", ".pytest_cache", "__pycache__", ".git"}


def _own_files():
    return [p for p in TRACKED_TEXT if not (SKIPPED_DIRS & set(p.relative_to(MODULE).parts)) and "egg-info" not in str(p)]


def test_the_repository_carries_everything_it_needs_to_run_on_its_own():
    for name in ("compose.yaml", "Makefile", ".env.example", ".gitignore", "Dockerfile", "docs/spec.md", "migrations/001_init.sql",
                 "scripts/prepare.sh", "scripts/lib/env.sh", "scripts/test-services.sh", "AGENTS.md", "README.md",
                 "docs/OPERATOR_GUIDE.md", ".specify/memory/constitution.md", "specs/glossary.md"):
        assert (MODULE / name).is_file(), name


def test_nothing_in_the_repository_refers_to_another_product():
    banned = re.compile(r"agentflow|agent-gateway|agent_gateway|gateway-db", re.IGNORECASE)
    offenders = [str(p.relative_to(MODULE)) for p in _own_files() if p.name != "test_module.py" and banned.search(p.read_text(errors="ignore"))]
    assert not offenders, offenders


def _service_names(compose: str) -> set[str]:
    return set(re.findall(r"^  ([a-z][a-z0-9_-]*):\s*$", compose.split("\nservices:\n", 1)[1].split("\nvolumes:", 1)[0], re.M))


def test_the_compose_file_runs_the_bot_with_its_own_database_and_publishes_nothing():
    compose = (MODULE / "compose.yaml").read_text()
    assert _service_names(compose) == {"db", "bot"}
    assert not re.search(r"^\s*ports:", compose, re.M) and "network_mode" not in compose
    assert "env_file: .env" in compose and "service_healthy" in compose


def test_the_bot_creates_only_its_own_tables():
    sql = (MODULE / "migrations" / "001_init.sql").read_text()
    assert not re.search(r"\b(CREATE\s+(ROLE|DATABASE|EXTENSION)|GRANT|DROP\s+DATABASE)\b", sql, re.IGNORECASE)


def test_no_code_imports_another_product_and_linking_depends_on_ports_only():
    for path in (MODULE / "src").rglob("*.py"):
        assert not re.search(r"^\s*(import|from)\s+(?!telegram|telegram_bot_gateway|__future__)\w*gateway", path.read_text(), re.M), path
    linking = (MODULE / "src/telegram_bot_gateway/application/linking.py").read_text()
    assert "adapters" not in linking


def test_the_template_names_no_model_organization_or_user():
    values = dict(l.split("=", 1) for l in (MODULE / ".env.example").read_text().splitlines() if "=" in l and not l.startswith("#"))
    assert values["DEFAULT_MODEL"] == "" and values["BOT_TOKEN"] == "" and values["CREDS_KEY"] == ""


def test_a_second_poller_is_reported_plainly(caplog):
    context = SimpleNamespace(error=Conflict("terminated by other getUpdates request"))
    with caplog.at_level(logging.ERROR):
        asyncio.run(handlers.on_error(None, context))
    assert "another bot instance is polling" in caplog.text


def test_the_heartbeat_file_is_written(tmp_path):
    target = tmp_path / "healthy"

    class Bot:
        async def get_me(self):
            return None

    async def go():
        task = asyncio.create_task(serve_mod._heartbeat(str(target), Bot()))
        await asyncio.sleep(0.05)
        task.cancel()

    asyncio.run(go())
    assert float(target.read_text()) > 0


def test_polling_drops_what_queued_while_offline_and_webhook_needs_no_extra_step(monkeypatch):
    seen = {}
    monkeypatch.setattr(Application, "run_polling", lambda self, **kw: seen.update(kw))
    monkeypatch.setattr(Application, "run_webhook", lambda self, **kw: seen.update(kw, webhook=True))
    cfg = Settings("123:abc", "http://x", "m", "d", "k")
    serve_mod.serve(cfg)
    assert seen["drop_pending_updates"] is True and "webhook" not in seen
    serve_mod.serve(Settings("123:abc", "http://x", "m", "d", "k", webhook_url="https://b/h", webhook_secret="s"))
    assert seen["secret_token"] == "s" and seen["webhook"] is True and seen["drop_pending_updates"] is True
