"""Felles oppsett for testene: ferske nøkler og en loggfil i tmp for hver test.

Hvorfor: vault krever nøkler fra miljøvariabler og skriver til en fil. Uten dette
ville testene skrevet i prosjektmappen og vært avhengige av terminalen din.
Nøklene her er tilfeldige og gjelder bare inne i én test.
"""

from __future__ import annotations

import pytest

from ui.human_key import ENV_HUMAN_KEY
from ui.state import ENV_EXECUTOR
from vault.crypto import ENV_LOG_KEY, ENV_PSEUDONYM_KEY, new_log_key, new_pseudonym_key
from vault.identity import ENV_TABLE_PATH
from vault.store import ENV_LOG_PATH

# Menneskenøkkelen testene bruker. Den står her som en EKSPLISITT, fast verdi
# og ikke som en tilfeldig: `/api/respond` feiler lukket uten nøkkel, så uten
# denne ville hele godkjenningsflyten svart 503 i testene. At den er fast gjør
# at en test kan sende den i et HTTP-hode uten å gå veien om en fikstur.
#
# Dette er ikke en hemmelighet, og den gjelder bare inne i en testkjøring.
# Den ekte lages av `python -m agent_gateway.oppsett` og står i den ignorerte
# .lonewatch-agent-env.
HUMAN_KEY = "test-menneskenokkel-bare-for-tester-0001"

# To nøkler, slik at en test kan vise at to ulike mennesker får to ulike
# pseudonymer i loggen. Den andre er med i miljøet hele tiden.
HUMAN_KEY_TWO = "test-menneskenokkel-nummer-to-0002"

HUMAN_KEYS_ENV = f"{HUMAN_KEY},{HUMAN_KEY_TWO}"


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
    patch.setenv(ENV_HUMAN_KEY, HUMAN_KEYS_ENV)
    # Ingen test sender e-post. Er LONEWATCH_EXECUTOR satt i terminalen din,
    # skal det ikke smitte inn i testene.
    patch.delenv(ENV_EXECUTOR, raising=False)
    yield base
    patch.undo()


@pytest.fixture(autouse=True)
def lonewatch_env(tmp_path, monkeypatch):
    monkeypatch.setenv(ENV_LOG_KEY, new_log_key())
    monkeypatch.setenv(ENV_PSEUDONYM_KEY, new_pseudonym_key())
    monkeypatch.setenv(ENV_LOG_PATH, str(tmp_path / "log.jsonl"))
    monkeypatch.setenv(ENV_TABLE_PATH, str(tmp_path / "pseudonyms.enc"))
    monkeypatch.setenv(ENV_HUMAN_KEY, HUMAN_KEYS_ENV)
    monkeypatch.delenv(ENV_EXECUTOR, raising=False)
    return tmp_path
