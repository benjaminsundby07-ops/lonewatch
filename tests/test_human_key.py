"""Menneskenøkkelen i seg selv: hvem slipper inn, og hva loggen får vite.

Porten over HTTP er angrepet i `tests/attack/test_attack_self_approval.py`.
Denne filen måler delene under: hvordan nøkler leses fra miljøet, hvordan
operatør-iden blir til, og hva som skjer når oppsettet er galt.

Ingen nøkkel her er en hemmelighet, og ingen av dem skrives til disk.
"""

from __future__ import annotations

import pytest

from ui.human_key import (
    ENV_AGENT_KEY,
    ENV_HUMAN_KEY,
    HUMAN_KEY_HEADER,
    MIN_KEY_CHARS,
    HumanKeyOff,
    HumanKeyRefused,
    check_human_key,
    configured_keys,
    is_configured,
    operator_id,
)
from ui.state import DemoState

EN = "noekkel-nummer-en-0123456789"
TO = "noekkel-nummer-to-0123456789"


def env(human: str | None = None, agent: str | None = None) -> dict[str, str]:
    ut = {}
    if human is not None:
        ut[ENV_HUMAN_KEY] = human
    if agent is not None:
        ut[ENV_AGENT_KEY] = agent
    return ut


# ---------------------------------------------------------------------------
# hvilke noekler gjelder
# ---------------------------------------------------------------------------


def test_no_key_configured_means_no_keys():
    assert configured_keys(env()) == ()
    assert configured_keys(env("")) == ()
    assert configured_keys(env("   ")) == ()


def test_one_key_is_one_key():
    assert configured_keys(env(EN)) == (EN,)
    assert configured_keys(env(f"  {EN}  ")) == (EN,)


@pytest.mark.parametrize("skille", [",", ";", " ", "\t", ", ", "\n"])
def test_several_keys_can_be_listed(skille):
    """Én nøkkel per person er hele grunnen til at listen finnes.

    Med én delt nøkkel kan loggen bare si «noen med menneskenøkkelen». Med én
    per person sier den hvem - og det er det nærmeste denne modellen kommer
    BankID.
    """
    assert configured_keys(env(f"{EN}{skille}{TO}")) == (EN, TO)


def test_a_key_that_is_too_short_is_thrown_away():
    """En nøkkel på fire tegn ville sett ut som et forsvar og ikke vært et."""
    kort = "x" * (MIN_KEY_CHARS - 1)
    assert configured_keys(env(kort)) == ()
    assert configured_keys(env(f"{kort},{EN}")) == (EN,)


def test_the_same_key_twice_counts_once():
    assert configured_keys(env(f"{EN},{EN}")) == (EN,)


# ---------------------------------------------------------------------------
# hvem slipper inn
# ---------------------------------------------------------------------------


def test_the_right_key_is_let_in():
    assert check_human_key(EN, env(EN)) == operator_id(EN)
    assert check_human_key(f"  {EN}  ", env(EN)) == operator_id(EN)


def test_each_configured_key_is_let_in_and_gets_its_own_identity():
    e = env(f"{EN},{TO}")
    assert check_human_key(EN, e) == operator_id(EN)
    assert check_human_key(TO, e) == operator_id(TO)
    assert operator_id(EN) != operator_id(TO)


@pytest.mark.parametrize(
    "gitt",
    [None, "", "   ", "x", EN + "x", EN[:-1], EN.upper(), "noekkel-nummer-en", "æøå" * 10],
)
def test_a_wrong_key_is_refused(gitt):
    with pytest.raises(HumanKeyRefused):
        check_human_key(gitt, env(EN))


def test_a_non_ascii_key_does_not_crash_the_comparison():
    """`hmac.compare_digest` kaster TypeError på tekst som ikke er ASCII.

    Et HTTP-hode noen har fylt med norske tegn skal gi «nei», ikke en
    500-feil. Og en nøkkel MED norske tegn i skal virke.
    """
    noekkel = "nøkkel-med-æøå-0123456789"
    with pytest.raises(HumanKeyRefused):
        check_human_key("æøå", env(EN))
    assert check_human_key(noekkel, env(noekkel)) == operator_id(noekkel)


# ---------------------------------------------------------------------------
# fail closed
# ---------------------------------------------------------------------------


def test_without_a_configured_key_nothing_is_let_in():
    """Fail closed. En port som åpner seg når oppsettet mangler er ingen port."""
    for gitt in (None, "", EN, "hva som helst"):
        with pytest.raises(HumanKeyOff):
            check_human_key(gitt, env())
    assert is_configured(env()) is False


def test_the_agent_key_can_never_be_the_human_key():
    """Er de to like, slås godkjenningen AV - den blir ikke åpen for agenten.

    Et oppsett der agentnøkkelen også godkjenner har ikke noe skille mellom
    «en agent ba om dette» og «et menneske godkjente det». Da skal ingen
    slippe gjennom, ikke bare agenten: ellers ville feilen vært usynlig.
    """
    e = env(EN, agent=EN)
    for gitt in (EN, None, "feil"):
        with pytest.raises(HumanKeyOff):
            check_human_key(gitt, e)
    assert is_configured(e) is False


def test_one_shared_key_in_a_list_is_enough_to_shut_it_off():
    e = env(f"{EN},{TO}", agent=TO)
    with pytest.raises(HumanKeyOff):
        check_human_key(EN, e)
    assert is_configured(e) is False


def test_a_different_agent_key_is_fine():
    e = env(EN, agent=TO)
    assert check_human_key(EN, e) == operator_id(EN)
    assert is_configured(e) is True
    # Og agentnøkkelen godkjenner ingenting.
    with pytest.raises(HumanKeyRefused):
        check_human_key(TO, e)


# ---------------------------------------------------------------------------
# hva loggen faar vite
# ---------------------------------------------------------------------------


def test_the_operator_id_cannot_be_read_back_as_the_key():
    """Iden er en hash. Nøkkelen skal ikke kunne leses ut av den."""
    ident = operator_id(EN)
    assert EN not in ident
    assert ident.startswith("human-key:")
    assert len(ident) == len("human-key:") + 16
    # Samme nøkkel gir samme id hver gang.
    assert operator_id(EN) == operator_id(EN)


def test_the_log_gets_a_pseudonym_that_follows_the_key():
    state = DemoState()
    try:
        en = state.operator_pseudonym(operator_id(EN))
        to = state.operator_pseudonym(operator_id(TO))
        assert en.startswith("emp_") and to.startswith("emp_")
        assert en != to
        # Og pseudonymet inneholder ikke noekkelen.
        assert EN not in en and TO not in to
    finally:
        state.close()


def test_a_respond_without_an_operator_falls_back_to_the_demo_employee():
    """`DemoState` kalt direkte (slik testene gjør) skal fortsatt virke.

    Menneskenøkkelen er en port på HTTP-laget. `DemoState.respond()` er
    fortsatt kallbar uten den, og da bruker loggen demoens ansatt. Det er en
    bekvemmelighet for testene, og den står i ui/LIMITS.md.
    """
    state = DemoState()
    try:
        out = state.submit_custom(
            action_type="transfer_money", amount="450000", recipient="NO93 8601 1117 947"
        )
        request_id = out["card"]["request"]["id"]
        svar = state.respond(request_id, approved=True, typed_amount="450 000")
        assert svar["ok"] is True
        assert svar["card"]["human"]["employee_pseudonym"].startswith("emp_")
    finally:
        state.close()


def test_the_header_name_is_not_the_agent_header():
    assert HUMAN_KEY_HEADER == "X-Lonewatch-Human-Key"
    from ui.app import AGENT_KEY_HEADER

    assert HUMAN_KEY_HEADER != AGENT_KEY_HEADER
