"""Felles oppsett for testene: ferske nøkler og en loggfil i tmp for hver test.

Hvorfor: vault krever nøkler fra miljøvariabler og skriver til en fil. Uten dette
ville testene skrevet i prosjektmappen og vært avhengige av terminalen din.
Nøklene her er tilfeldige og gjelder bare inne i én test.
"""

from __future__ import annotations

import pytest

from vault.crypto import ENV_LOG_KEY, ENV_PSEUDONYM_KEY, new_log_key, new_pseudonym_key
from vault.identity import ENV_TABLE_PATH
from vault.store import ENV_LOG_PATH


@pytest.fixture(autouse=True, scope="session")
def lonewatch_session_env(tmp_path_factory):
    """Sikkerhetsnett for hele testkjøringen: ingen test rører loggen i prosjektmappen.

    Hvorfor denne i tillegg til den under: en fikstur med modul- eller sesjonsomfang
    settes opp FØR funksjonsnære fiksturer. `server` i test_ui.py er modulomfang og
    importerer ui.app, som lager en DemoState med én gang. Uten denne fiksturen ville
    den peke på den ekte lonewatch_log.jsonl.
    """
    base = tmp_path_factory.mktemp("lonewatch_session")
    patch = pytest.MonkeyPatch()
    patch.setenv(ENV_LOG_KEY, new_log_key())
    patch.setenv(ENV_PSEUDONYM_KEY, new_pseudonym_key())
    patch.setenv(ENV_LOG_PATH, str(base / "log.jsonl"))
    patch.setenv(ENV_TABLE_PATH, str(base / "pseudonyms.enc"))
    yield base
    patch.undo()


@pytest.fixture(autouse=True)
def lonewatch_env(tmp_path, monkeypatch):
    monkeypatch.setenv(ENV_LOG_KEY, new_log_key())
    monkeypatch.setenv(ENV_PSEUDONYM_KEY, new_pseudonym_key())
    monkeypatch.setenv(ENV_LOG_PATH, str(tmp_path / "log.jsonl"))
    monkeypatch.setenv(ENV_TABLE_PATH, str(tmp_path / "pseudonyms.enc"))
    return tmp_path
