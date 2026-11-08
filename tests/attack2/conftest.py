"""Egen conftest for tests/attack2/.

Den autouse-fiksturen `lonewatch_env` i tests/conftest.py gir hver test ferske
noekler og en loggfil i tmp. Denne conftesten legger paa EN ting: en hard
sperre som nekter aa kjoere et angrep hvis loggstien ved et uhell ikke peker
paa tmp. Ingen test i runde to skal kunne roere brukerens ekte logg.
"""

from __future__ import annotations

import os
import tempfile

import pytest

from vault.store import ENV_LOG_PATH


@pytest.fixture(autouse=True)
def refuse_to_touch_real_log():
    """Stopper testen om LONEWATCH_LOG_PATH ikke ligger i et tmp-omraade."""
    path = os.environ.get(ENV_LOG_PATH, "")
    tmp_root = os.path.realpath(tempfile.gettempdir())
    resolved = os.path.realpath(path) if path else ""
    # pytest sine tmp_path ligger under tempdir (eller /private/var/... paa mac,
    # som realpath normaliserer). Godta ogsaa "pytest-of-" i stien.
    ok = bool(resolved) and (
        resolved.startswith(tmp_root)
        or "pytest-of-" in resolved
        or "/pytest-" in resolved
        or resolved.startswith("/private/")
    )
    assert ok, (
        f"NEKTER aa kjoere: LONEWATCH_LOG_PATH={path!r} peker ikke paa en "
        "tmp-fil. Et angrep skal aldri roere den ekte loggen."
    )
    yield
