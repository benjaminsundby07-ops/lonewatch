"""Angrep 12 (nytt i runde tre): «Bryt loggen»-ruten.

`POST /api/tamper` kjoerer et ekte angrep paa loggen og lar verifiseringen
svare. Det er en knapp som bevisst gjoer noe destruktivt, og den leser
loggnoekkelen. Da maa den angripes foer den slippes:

  - kan den naas uten menneskenoekkelen? (nei - se test_attack_routes.py)
  - kan den som kaller peke demoen paa en ANNEN fil, eller sende inn sin egen
    noekkel?
  - roerer den den ekte loggen?
  - laekker den noekkelen, en filsti eller klartekst fra loggen?
  - kan «full» (den dokumenterte grensen) komme til aa se ut som en feil, eller
    en feil se ut som grensen?

Alt kjoerer mot tmp-loggen fiksturen satte opp. `refuse_to_touch_real_log`
stopper testen hvis loggstien ikke er i tmp.
"""

from __future__ import annotations

import pytest
from attack_lib2 import refuse_to_touch_real_log  # noqa: F401  (autouse: aldri roer den ekte loggen)

from attack_lib2 import human_headers, live_app

from vault.tamper_demo import ATTACK_EXPECT_DETECTED, ATTACK_TITLES, ATTACKS


def _full_log(live_app) -> None:
    """En logg som er lang nok for alle fire angrepene."""
    live_app.drain_feed()
    _, snap = live_app.get("/api/state", headers=human_headers())
    assert snap["log"]["lines"] >= 3, snap["log"]["lines"]


# ---------------------------------------------------------------------------
# HOLDER: kroppen eier ingenting annet enn hvilket angrep.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "ekstra",
    [
        {"path": "/etc/passwd"},
        {"path": "../../lonewatch_log.jsonl"},
        {"key": "ZmFrZS1ub2trZWwtc29tLWlra2UtZXItZW4tbm9ra2Vs"},
        {"real": True},
        {"expected_detected": True},
        {"detected": False},
    ],
)
def test_the_caller_cannot_point_the_demo_at_another_file_or_key(live_app, ekstra):
    """`extra="forbid"`: ett felt, og alt annet er 422.

    Hvorfor dette er det viktigste angrepet mot ruten: kunne kroppen oppgi
    `path`, ville knappen vaert en vilkaarlig fil-leser bak ett HTTP-kall. Og
    kunne den oppgi `detected` eller `expected_detected`, kunne et angrep
    FORTELLE nettsiden at det ble oppdaget.
    """
    _full_log(live_app)
    body = {"attack": "endre", **ekstra}
    status, _ = live_app.post("/api/tamper", body, headers=human_headers())
    assert status == 422, f"{ekstra} ble ikke avvist ({status})"


def test_an_unknown_attack_is_a_clean_409_not_a_500(live_app):
    _full_log(live_app)
    for navn in ("tull", "", "ENDRE", "endre;slett", "../endre", "x" * 15):
        status, _ = live_app.post(
            "/api/tamper", {"attack": navn}, headers=human_headers()
        )
        assert status in (409, 422), f"«{navn}» svarte {status}"


def test_a_too_long_attack_name_is_refused_by_the_field_limit(live_app):
    status, _ = live_app.post(
        "/api/tamper", {"attack": "x" * 5000}, headers=human_headers()
    )
    assert status == 422


# ---------------------------------------------------------------------------
# HOLDER: den ekte loggen blir ikke roert.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("attack", ATTACKS)
def test_the_real_log_is_untouched_by_every_attack(live_app, attack):
    """Fire angrep, og loggen staar der etterpaa - samme antall linjer, hel kjede.

    `tamper_demo` svarer selv `real_log_untouched` (fingeravtrykk foer og etter),
    men vi tror ikke paa det feltet: vi maaler fra UTSIDEN ogsaa, gjennom
    /api/state og /api/verify.
    """
    _full_log(live_app)
    _, foer = live_app.get("/api/state", headers=human_headers())
    _, verify_foer = live_app.get("/api/verify")

    status, r = live_app.post("/api/tamper", {"attack": attack}, headers=human_headers())
    assert status == 200, r
    assert r["real_log_untouched"] is True

    _, etter = live_app.get("/api/state", headers=human_headers())
    _, verify_etter = live_app.get("/api/verify")
    assert etter["log"]["lines"] == foer["log"]["lines"], "angrepet endret linjeantallet"
    assert verify_etter["ok"] is True, "den ekte loggen stemmer ikke etter angrepet"
    assert verify_etter["head"] == verify_foer["head"], "topphashen flyttet seg"


def test_running_every_attack_in_a_row_still_leaves_the_log_whole(live_app):
    """Og fire angrep etter hverandre gjoer ikke mer skade enn ett."""
    _full_log(live_app)
    _, verify_foer = live_app.get("/api/verify")
    for attack in ATTACKS:
        status, _ = live_app.post(
            "/api/tamper", {"attack": attack}, headers=human_headers()
        )
        assert status == 200
    _, verify_etter = live_app.get("/api/verify")
    assert verify_etter["ok"] is True
    assert verify_etter["head"] == verify_foer["head"]


# ---------------------------------------------------------------------------
# HOLDER: svaret er ærlig, og det laekker ingenting.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("attack", ATTACKS)
def test_the_answer_matches_what_the_documentation_says(live_app, attack):
    """`detected` stemmer med `ATTACK_EXPECT_DETECTED` - ogsaa for «full».

    «full» staar med `expected_detected=False` fordi det er sant: den som har
    loggnoekkelen kan signere et nytt anker. Skulle den dagen komme der «full»
    BLIR oppdaget, feiler denne testen - og da skal baade koden og
    dokumentasjonen endres i samme slengen.
    """
    _full_log(live_app)
    status, r = live_app.post("/api/tamper", {"attack": attack}, headers=human_headers())
    assert status == 200, r
    assert r["expected_detected"] == ATTACK_EXPECT_DETECTED[attack]
    assert r["detected"] == ATTACK_EXPECT_DETECTED[attack], (
        f"«{attack}»: detected={r['detected']}, dokumentasjonen sier "
        f"{ATTACK_EXPECT_DETECTED[attack]}"
    )
    assert r["as_documented"] is True
    assert r["title"] == ATTACK_TITLES[attack]
    # Begge hashene er med. Det er sammenligningen som er beviset.
    assert "head_hash_before" in r and "head_hash_after" in r


@pytest.mark.parametrize("attack", ATTACKS)
def test_the_answer_leaks_no_key_and_no_absolute_path(live_app, attack):
    """Svaret gaar til en nettleser. Da skal det ikke ha en noekkel eller en sti.

    `real_log_before`/`real_log_after` har med vilje bare NAVNET paa filen,
    sha256 og stoerrelsen - ikke stien.
    """
    import os

    _full_log(live_app)
    _, r = live_app.post("/api/tamper", {"attack": attack}, headers=human_headers())
    blob = str(r)
    for env in ("LONEWATCH_LOG_KEY", "LONEWATCH_PSEUDONYM_KEY", "LONEWATCH_HUMAN_KEY"):
        assert env not in blob
        verdi = os.environ.get(env) or ""
        if verdi:
            for del_ in verdi.split(","):
                assert del_.strip() not in blob, f"{env} laekket i svaret"
    assert "/Users/" not in blob
    assert "/private/" not in blob
    assert "/tmp" not in blob


def test_an_empty_log_is_a_409_and_not_a_pretend_result(live_app):
    """Paa en tom logg nekter ruten. Den later ikke som den brøt noe.

    Det er det ærlige svaret: er det ingenting i loggen, er det ingenting aa
    bryte, og et «ikke oppdaget» ville sett ut som en svakhet den ikke er.
    """
    _, snap = live_app.get("/api/state", headers=human_headers())
    assert snap["log"]["lines"] == 0, "fiksturen skal gi en tom logg"
    status, body = live_app.post(
        "/api/tamper", {"attack": "endre"}, headers=human_headers()
    )
    assert status == 409
    assert "finnes ikke" in str(body) or "tom" in str(body).lower(), body
    # Og beskjeden navngir ikke mappen loggen ligger i. Funnet av denne testen:
    # `TamperDemoError` skriver full sti, som er riktig i en terminal og galt i
    # et HTTP-svar. `ui.app._no_paths` kutter den til filnavnet.
    assert "/Users/" not in str(body)
    assert "/private/" not in str(body)
    assert "/var/" not in str(body)


def test_the_button_list_is_open_but_carries_no_log_data(live_app):
    """GET /api/tamper er aapen (fire norske titler), men har ingen loggdata."""
    status, body = live_app.get("/api/tamper")
    assert status == 200
    navn = [a["attack"] for a in body["attacks"]]
    assert navn == list(ATTACKS)
    for a in body["attacks"]:
        assert a["title"] == ATTACK_TITLES[a["attack"]]
    blob = str(body)
    assert "hash" not in blob.lower()
    assert "LONEWATCH" not in blob
