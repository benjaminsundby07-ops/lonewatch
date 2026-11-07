"""Tester for vault: kryptering, hash-kjede, pseudonymer, minimering og Etter-listen."""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone

import pytest
from cryptography.fernet import Fernet

from contracts import ActionRequest, ActionType, Decision, HumanResponse, Risk, SandboxReport, TrapEvent, Verdict
from vault import (
    ENV_LOG_KEY,
    NotAuthorized,
    Vault,
    VaultKeyError,
    build_after_actions,
    mask_recipient,
    new_log_key,
    pseudonymize,
    redact_payload,
    register_employee,
    reveal,
)

T0 = datetime(2026, 1, 15, 9, 0, tzinfo=timezone.utc)
SECRET_ACCOUNT = "NO9386011117947"


def make_request(**over) -> ActionRequest:
    data = dict(
        id="req_0003",
        ts=T0,
        agent_id="finance_agent",
        action_type=ActionType.TRANSFER_MONEY,
        summary="Haster, leverandøren venter",
        amount=10_000_000.0,
        recipient=SECRET_ACCOUNT,
        recipient_known=False,
        reversible=False,
    )
    data.update(over)
    return ActionRequest(**data)


def make_decision(**over) -> Decision:
    data = dict(
        request_id="req_0003",
        ts=T0 + timedelta(seconds=1),
        verdict=Verdict.RED,
        risk=Risk.HIGH,
        reasons=["unknown_recipient", "amount_over_limit", "irreversible"],
        consequence_text="Overfører 10 000 000 kr til ukjent konto. Kan ikke angres.",
        requires_typed_amount=True,
    )
    data.update(over)
    return Decision(**data)


def filled_vault() -> Vault:
    """Tre linjer: forespørsel, avgjørelse, menneskets svar."""
    vault = Vault()
    req = make_request()
    dec = make_decision()
    human = HumanResponse(
        request_id=req.id,
        ts=dec.ts + timedelta(seconds=12),
        employee_pseudonym=pseudonymize("ansatt-007"),
        approved=False,
        seconds_to_decide=12.0,
    )
    vault.append("request", req.model_dump(mode="json"), ts=req.ts)
    vault.append("decision", dec.model_dump(mode="json"), ts=dec.ts)
    vault.append("human", human.model_dump(mode="json"), ts=human.ts)
    return vault


def read_lines(vault: Vault) -> list[str]:
    return vault.path.read_text(encoding="utf-8").splitlines()


def write_lines(vault: Vault, lines: list[str]) -> None:
    vault.path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# ---------- 1. nøkler ----------

def test_missing_key_stops_with_a_clear_message(monkeypatch):
    monkeypatch.delenv(ENV_LOG_KEY, raising=False)
    with pytest.raises(VaultKeyError) as err:
        Vault()
    assert ENV_LOG_KEY in str(err.value)
    assert "gen_key" in str(err.value)


def test_garbage_key_is_rejected_instead_of_silently_replaced(monkeypatch):
    monkeypatch.setenv(ENV_LOG_KEY, "ikke-en-noekkel")
    with pytest.raises(VaultKeyError):
        Vault()


# ---------- 2. kryptert fil kan ikke leses uten nøkkel ----------

def test_log_file_is_unreadable_without_the_key():
    vault = filled_vault()
    raw = vault.path.read_text(encoding="utf-8")

    assert SECRET_ACCOUNT not in raw
    assert "transfer_money" not in raw
    assert "Haster" not in raw
    assert "10000000" not in raw
    assert all(line.startswith("gAAAAA") for line in raw.splitlines())

    # Riktig nøkkel ser alt.
    assert len(Vault().entries()) == 3


def test_wrong_key_cannot_read_or_verify_the_log():
    vault = filled_vault()
    other = Vault(path=vault.path, key=new_log_key())
    assert other.entries() == []
    assert other.verify() == 0  # første linje kan ikke dekrypteres


# ---------- 3. endring og sletting paa disk ----------

def test_changed_ciphertext_points_to_the_right_seq():
    vault = filled_vault()
    lines = read_lines(vault)
    target = lines[1]
    pos = len(target) // 2
    lines[1] = target[:pos] + ("A" if target[pos] != "A" else "B") + target[pos + 1 :]
    write_lines(vault, lines)

    assert Vault(path=vault.path).verify() == 1


def test_rewritten_payload_with_the_key_points_to_the_right_seq():
    """Selv en angriper MED nøkkelen kan ikke endre en linje uten at kjeden knekker."""
    vault = filled_vault()
    fernet = Fernet(os.environ[ENV_LOG_KEY].encode("utf-8"))
    lines = read_lines(vault)

    entry = json.loads(fernet.decrypt(lines[1].encode("ascii")).decode("utf-8"))
    entry["payload"]["verdict"] = Verdict.ALLOW.value
    lines[1] = fernet.encrypt(json.dumps(entry, sort_keys=True).encode("utf-8")).decode("ascii")
    write_lines(vault, lines)

    assert Vault(path=vault.path).verify() == 1


def test_deleted_line_is_detected():
    vault = filled_vault()
    lines = read_lines(vault)
    del lines[1]
    write_lines(vault, lines)

    broken = Vault(path=vault.path).verify()
    assert broken is not None
    assert broken == 2  # linjen som naa ligger paa feil plass


def test_deleted_last_line_is_detected_by_the_open_vault():
    vault = filled_vault()
    lines = read_lines(vault)
    write_lines(vault, lines[:-1])

    assert vault.verify() == 2


def test_in_memory_tampering_is_detected():
    vault = filled_vault()
    vault._entries[1] = vault._entries[1].model_copy(update={"payload": {"verdict": "allow"}})
    assert vault.verify() == 1


def test_untouched_log_verifies():
    vault = filled_vault()
    assert vault.verify() is None
    assert Vault(path=vault.path).verify() is None
    assert Vault().verify() is None  # tom logg finnes ikke engang


def test_chain_continues_after_reopen():
    first = filled_vault()
    second = Vault(path=first.path)
    entry = second.append("sandbox", {"package_name": "x", "attempted_network": False})

    assert entry.seq == 3
    assert entry.prev_hash == first.entries()[-1].hash
    assert second.verify() is None
    assert len(Vault(path=first.path)) == 4


# ---------- 4. pseudonymer ----------

def test_same_employee_gives_same_pseudonym():
    first = pseudonymize("ansatt-007")
    assert first == pseudonymize("ansatt-007")
    assert first.startswith("emp_")
    assert len(first) == len("emp_") + 4
    assert "ansatt" not in first
    assert first != pseudonymize("ansatt-008")


def test_pseudonym_depends_on_the_secret_key(monkeypatch):
    before = pseudonymize("ansatt-007")
    monkeypatch.setenv("LONEWATCH_PSEUDONYM_KEY", "en helt annen noekkel for test")
    assert pseudonymize("ansatt-007") != before


def test_pseudonym_cannot_be_reversed_without_admin():
    pseudonym = register_employee("ansatt-007")

    with pytest.raises(NotAuthorized):
        reveal(pseudonym, "finance")
    with pytest.raises(NotAuthorized):
        reveal(pseudonym, "employee")

    assert reveal(pseudonym, "admin") == "ansatt-007"
    assert reveal("emp_0000", "admin") is None


def test_name_table_is_encrypted_on_disk():
    pseudonym = register_employee("ansatt-007")
    table_raw = os.environ["LONEWATCH_PSEUDONYM_TABLE"]
    content = open(table_raw, encoding="utf-8").read()
    assert "ansatt-007" not in content
    assert pseudonym not in content


def test_log_never_contains_the_employee_name():
    vault = filled_vault()
    for entry in vault.entries():
        assert "ansatt-007" not in json.dumps(entry.payload)


# ---------- 5. dataminimering ----------

def test_allow_keeps_only_type_risk_and_verdict():
    allow = make_decision(verdict=Verdict.ALLOW, risk=Risk.LOW, reasons=[],
                          consequence_text="Oppdaterer kalenderen.", requires_typed_amount=False)
    out = redact_payload("decision", allow.model_dump(mode="json"))
    assert out == {"request_id": "req_0003", "risk": "low", "verdict": "allow"}


def test_red_keeps_details_but_masks_recipient():
    out = redact_payload("request", make_request().model_dump(mode="json"))
    assert out["recipient"] == "****7947"
    assert SECRET_ACCOUNT not in json.dumps(out)
    assert out["amount"] == 10_000_000.0
    assert out["reversible"] is False
    assert "summary" not in out  # agentens frie tekst kastes


def test_mask_recipient_shows_only_last_four():
    assert mask_recipient("NO9386011117947") == "****7947"
    assert mask_recipient("abc") == "****"
    assert mask_recipient(None) is None


def test_vault_can_log_in_redacted_mode():
    vault = Vault(redact=True)
    entry = vault.append("request", make_request().model_dump(mode="json"))
    assert entry.payload["recipient"] == "****7947"
    assert vault.verify() is None


# ---------- 6. Etter-listen ----------

def test_after_actions_from_a_full_incident():
    vault = filled_vault()
    vault.append("trap", TrapEvent(
        ts=T0, doc_id="doc_42", agent_id="it_helper",
        trap_id="trap_1", what_happened="Skjult tekst ba agenten sende kundelisten ut",
    ).model_dump(mode="json"))
    vault.append("sandbox", SandboxReport(
        ts=T0, package_name="nordlys-helper", attempted_network=True,
        destinations=["drop.example.net"], verdict="blocked", notes="simulert",
    ).model_dump(mode="json"))

    actions = build_after_actions(vault.entries())
    titles = [a.title for a in actions]

    assert "Sjekk den flaggede overføringen" in titles
    assert "Felle gikk av i et dokument" in titles
    assert "Tillegget prøvde aa sende data ut" in titles
    assert {a.owner_role for a in actions} >= {"finance", "security", "employee"}

    transfer = next(a for a in actions if a.title == "Sjekk den flaggede overføringen")
    assert "10 000 000 kr" in transfer.detail
    assert SECRET_ACCOUNT not in transfer.detail  # mottaker maskeres ogsaa her
    assert "****7947" in transfer.detail
    assert all(a.done is False for a in actions)


def test_after_actions_covers_blocked_package_and_personal_data():
    vault = Vault()
    pkg = make_request(id="req_0010", action_type=ActionType.INSTALL_PACKAGE,
                       amount=None, recipient=None, package_name="nordlys-helper-pro",
                       reversible=True, recipient_known=True)
    share = make_request(id="req_0011", action_type=ActionType.SHARE_DATA, amount=None,
                         recipient="partner@ukjent-firma.example", contains_personal_data=True)
    vault.append("request", pkg.model_dump(mode="json"))
    vault.append("decision", make_decision(request_id="req_0010", verdict=Verdict.BLOCK,
                                           consequence_text="Blokkert.",
                                           requires_typed_amount=False).model_dump(mode="json"))
    vault.append("request", share.model_dump(mode="json"))
    vault.append("decision", make_decision(request_id="req_0011", verdict=Verdict.RED,
                                           consequence_text="Deler persondata.",
                                           requires_typed_amount=False).model_dump(mode="json"))

    titles = [a.title for a in build_after_actions(vault.entries())]
    assert "Blokkert tillegg maa granskes" in titles
    assert "Persondata var paa vei ut" in titles


def test_after_actions_flags_a_human_approval():
    vault = Vault()
    vault.append("human", HumanResponse(
        request_id="req_0003", ts=T0, employee_pseudonym=pseudonymize("ansatt-007"),
        approved=True, typed_amount=10_000_000.0, seconds_to_decide=31.0,
    ).model_dump(mode="json"))

    actions = build_after_actions(vault.entries())
    assert [a.title for a in actions] == ["Rød forespørsel ble godkjent"]
    assert actions[0].owner_role == "security"


def test_after_actions_is_empty_for_a_calm_day():
    vault = Vault()
    calm = make_request(id="req_0001", action_type=ActionType.UPDATE_CALENDAR, amount=None,
                        recipient=None, recipient_known=True, reversible=True)
    vault.append("request", calm.model_dump(mode="json"))
    vault.append("decision", make_decision(request_id="req_0001", verdict=Verdict.ALLOW,
                                           risk=Risk.LOW, reasons=[],
                                           consequence_text="Oppdaterer kalenderen.",
                                           requires_typed_amount=False).model_dump(mode="json"))

    assert build_after_actions(vault.entries()) == []


def test_after_actions_survives_a_redacted_log():
    vault = Vault(redact=True)
    vault.append("request", make_request().model_dump(mode="json"))
    vault.append("decision", make_decision().model_dump(mode="json"))

    actions = build_after_actions(vault.entries())
    assert [a.title for a in actions] == ["Sjekk den flaggede overføringen"]
    assert SECRET_ACCOUNT not in actions[0].detail
