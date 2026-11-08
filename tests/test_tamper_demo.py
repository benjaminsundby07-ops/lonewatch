"""«Bryt loggen»: at de tre angrepene oppdages, at det fjerde ærlig ikke gjør det,
og at den ekte loggen aldri blir rørt.

Testene her stoler IKKE paa at modulen sier at loggen er uendret. De tar sitt
eget fingeravtrykk (sha256 + filstoerrelse) av loggen og ankeret foer og etter,
og sammenligner selv. En demo som skriver i den ekte loggen er verre enn ingen
demo, saa det er den viktigste testen i filen.

Angrep d (`full`) skal IKKE oppdages. Det er ikke en feil som venter paa aa bli
rettet; det er grensen i vault/LIMITS.md punkt 1 og 12, skrevet som en test slik
at den dagen noen tror den er lukket, staar det en test her som sier nei.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path

import pytest

from vault import Vault
from vault.anchor import anchor_path
from vault.crypto import ENV_LOG_KEY
from vault.store import VERIFY_TEXTS
from vault.tamper_demo import (
    ATTACK_ENDRE,
    ATTACK_EXPECT_DETECTED,
    ATTACK_FULL,
    ATTACK_KUTT,
    ATTACK_SLETT,
    ATTACKS,
    TamperDemoError,
    main,
    run_all,
    run_attack,
)

T0 = datetime(2026, 11, 7, 9, 0, tzinfo=timezone.utc)


def filled(n: int = 9) -> Vault:
    """En logg som ser ut som en ekte demo: forespørsel, avgjørelse, menneske.

    Ni linjer gir en tydelig midte (indeks 4) som er en roed avgjørelse, slik at
    `endre` treffer det angriperen faktisk ville vaert ute etter.
    """
    v = Vault()
    for i in range(n):
        if i % 3 == 0:
            v.append(
                "request",
                {"id": f"req_{i}", "action_type": "transfer_money", "amount": 1000.0 + i},
                ts=T0,
            )
        elif i % 3 == 1:
            v.append(
                "decision",
                {"request_id": f"req_{i - 1}", "verdict": "red", "risk": "high"},
                ts=T0,
            )
        else:
            v.append("human", {"request_id": f"req_{i - 2}", "approved": False}, ts=T0)
    return v


def traps_only(n: int = 7) -> Vault:
    """En logg uten avgjørelser, menneskesvar eller beløp: ingenting aa foretrekke."""
    v = Vault()
    for i in range(n):
        v.append(
            "trap",
            {"doc_id": f"doc_{i}", "agent_id": "a", "trap_id": f"t{i}", "what_happened": "x"},
            ts=T0,
        )
    return v


def own_fingerprint(log: Path) -> dict[str, tuple[str, int] | None]:
    """Vaart EGET avtrykk av loggen og ankeret. Vi spoer ikke modulen."""

    def one(p: Path) -> tuple[str, int] | None:
        if not p.exists():
            return None
        data = p.read_bytes()
        return sha256(data).hexdigest(), len(data)

    return {"log": one(log), "anchor": one(anchor_path(log))}


# ---------------------------------------------------------------------------
# de tre angrepene som skal oppdages
# ---------------------------------------------------------------------------


def test_endre_en_linje_midt_i_loggen_oppdages():
    v = filled(9)
    result = run_attack(ATTACK_ENDRE, path=v.path)

    assert result.detected is True
    assert result.reason == "chain"
    # Midten av ni linjer er indeks 4, og den er en roed avgjørelse.
    assert result.broken_seq == 4
    assert "rød" in result.what_we_did and "tillatt" in result.what_we_did
    assert result.lines_before == result.lines_after == 9
    # Angrepet rørte ikke ankeret, saa det skal se likt ut foer og etter.
    assert result.anchor_before == result.anchor_after


def test_slett_en_linje_midt_i_loggen_oppdages():
    v = filled(9)
    result = run_attack(ATTACK_SLETT, path=v.path)

    assert result.detected is True
    assert result.reason == "chain"
    # Linje 4 er borte, saa den foerste som staar paa feil plass er seq=5.
    assert result.broken_seq == 5
    assert result.lines_before == 9
    assert result.lines_after == 8
    assert result.anchor_before == result.anchor_after


def test_kutt_av_halen_oppdages_av_ankeret():
    v = filled(9)
    result = run_attack(ATTACK_KUTT, path=v.path)

    assert result.detected is True
    # Dette er det hash-kjeden alene IKKE ser. Det maa vaere ankeret som svarer.
    assert result.reason == "log_truncated"
    assert result.lines_before == 9
    assert result.lines_after == 7
    # Ankeret staar fortsatt paa ni linjer, og det er nettopp derfor det ser det.
    assert result.anchor_before is not None
    assert result.anchor_before["lines"] == 9
    assert result.anchor_before == result.anchor_after
    assert result.head_hash_before != result.head_hash_after


def test_kjeden_alene_ville_ikke_sett_kuttet():
    """Hvorfor ankeret trengs: det som staar igjen ER en gyldig kjede."""
    from contracts import verify_chain

    v = filled(9)
    lines = v.path.read_text(encoding="utf-8").splitlines()[:-2]
    v.path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    anchor_path(v.path).unlink()

    assert verify_chain(Vault(path=v.path).entries()) is None


# ---------------------------------------------------------------------------
# det fjerde: grensen, sagt ærlig
# ---------------------------------------------------------------------------


def test_full_omskriving_oppdages_IKKE_og_det_er_det_aerlige_svaret():
    v = filled(9)
    result = run_attack(ATTACK_FULL, path=v.path)

    assert result.detected is False
    assert result.expected_detected is False
    assert result.as_documented is True
    assert result.reason == "ok"
    assert result.broken_seq is None
    assert result.lines_before == result.lines_after == 9

    # Resultatet skal si hvorfor, og hva som faktisk lukker hullet.
    assert "grensen" in result.explanation
    assert "UTENFOR maskinen" in result.explanation
    assert "LIMITS" in result.explanation

    # Og det som ER synlig: siste hash er en annen. Det er hele poenget med aa
    # skrive den ned utenfor maskinen.
    assert result.head_hash_before != result.head_hash_after
    assert result.anchor_after is not None
    assert result.anchor_after["hash"] == result.head_hash_after
    assert result.anchor_before != result.anchor_after


def test_full_omskriving_gir_en_logg_en_fersk_leser_godtar():
    """Ikke bare at demoen sier «ok» - at en helt uavhengig Vault ogsaa gjoer det.

    Ellers kunne demoen pyntet paa svaret sitt. Vi gjentar angrepet selv her.
    """
    v = filled(9)
    assert run_attack(ATTACK_FULL, path=v.path).detected is False
    # Den ekte loggen er fortsatt den ekte, og den verifiserer fortsatt.
    assert Vault(path=v.path).verify() is None


def test_alle_fire_svarer_som_dokumentert():
    v = filled(9)
    results = run_all(path=v.path)

    assert [r.attack for r in results] == list(ATTACKS)
    for result in results:
        assert result.detected is ATTACK_EXPECT_DETECTED[result.attack]
        assert result.as_documented is True


# ---------------------------------------------------------------------------
# den ekte loggen skal aldri roeres
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("attack", ATTACKS)
def test_den_ekte_loggen_og_ankeret_er_uendret_etterpaa(attack):
    v = filled(9)
    before = own_fingerprint(v.path)
    assert before["log"] is not None and before["anchor"] is not None

    result = run_attack(attack, path=v.path)

    assert own_fingerprint(v.path) == before
    assert result.real_log_untouched is True
    # Og modulens eget avtrykk skal stemme med vaart.
    assert result.real_log_before["log"]["sha256"] == before["log"][0]
    assert result.real_log_before["log"]["size"] == before["log"][1]
    assert result.real_log_after == result.real_log_before


def test_alle_fire_etter_hverandre_lar_loggen_staa():
    v = filled(9)
    before = own_fingerprint(v.path)
    run_all(path=v.path)
    assert own_fingerprint(v.path) == before
    assert Vault(path=v.path).verify() is None


@pytest.mark.parametrize("attack", ATTACKS)
def test_den_midlertidige_mappen_ryddes_bort(attack, monkeypatch):
    """Kopien skal ikke ligge igjen paa disk etter demoen."""
    import tempfile

    laget: list[Path] = []
    ekte = tempfile.mkdtemp

    def spor(*args, **kwargs):
        path = ekte(*args, **kwargs)
        laget.append(Path(path))
        return path

    monkeypatch.setattr(tempfile, "mkdtemp", spor)

    v = filled(9)
    run_attack(attack, path=v.path)

    assert laget, "demoen laget ingen midlertidig mappe - da jobbet den et annet sted"
    for path in laget:
        assert not path.exists(), f"{path} ligger igjen"


def test_kopien_ligger_ikke_i_samme_mappe_som_den_ekte_loggen():
    v = filled(9)
    before = {p.name for p in v.path.parent.iterdir()}
    run_all(path=v.path)
    assert {p.name for p in v.path.parent.iterdir()} == before


# ---------------------------------------------------------------------------
# feiler lukket
# ---------------------------------------------------------------------------


def test_feiler_lukket_naar_loggen_ikke_finnes(tmp_path):
    with pytest.raises(TamperDemoError) as exc:
        run_attack(ATTACK_ENDRE, path=tmp_path / "finnes-ikke.jsonl")
    assert "finnes ikke" in str(exc.value)


def test_feiler_lukket_naar_loggen_er_tom(tmp_path):
    tom = tmp_path / "tom.jsonl"
    tom.write_text("", encoding="utf-8")
    with pytest.raises(TamperDemoError) as exc:
        run_attack(ATTACK_ENDRE, path=tom)
    assert "tom" in str(exc.value)


@pytest.mark.parametrize("attack", [ATTACK_ENDRE, ATTACK_SLETT])
def test_feiler_lukket_naar_loggen_er_for_kort_for_en_midte(attack):
    """«Midt i loggen» med to linjer er ikke midt i noe. Da gjoer vi det ikke."""
    v = filled(2)
    with pytest.raises(TamperDemoError) as exc:
        run_attack(attack, path=v.path)
    assert "minst 3" in str(exc.value)


def test_feiler_lukket_paa_ukjent_angrep():
    v = filled(9)
    with pytest.raises(TamperDemoError) as exc:
        run_attack("slett-alt", path=v.path)
    assert "Ukjent angrep" in str(exc.value)


def test_feiler_lukket_uten_noekkel(monkeypatch):
    v = filled(9)
    monkeypatch.delenv(ENV_LOG_KEY, raising=False)
    with pytest.raises(TamperDemoError) as exc:
        run_attack(ATTACK_ENDRE, path=v.path)
    assert ENV_LOG_KEY in str(exc.value)


def test_feiler_lukket_naar_loggen_alt_er_oedelagt_foer_vi_begynner():
    """Demoen skal ikke ta æren for noe andre har gjort."""
    v = filled(9)
    lines = v.path.read_text(encoding="utf-8").splitlines()
    lines[4] = lines[3]  # samme linje to ganger: kjeden knekker
    v.path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    with pytest.raises(TamperDemoError) as exc:
        run_attack(ATTACK_ENDRE, path=v.path)
    assert "FØR angrepet" in str(exc.value)


def test_feiler_lukket_naar_ankeret_mangler():
    """Uten anker kan demoen ikke vise angrep c ærlig, saa den stopper."""
    v = filled(9)
    anchor_path(v.path).unlink()

    with pytest.raises(TamperDemoError) as exc:
        run_attack(ATTACK_KUTT, path=v.path)
    assert "FØR angrepet" in str(exc.value)
    assert "anker" in str(exc.value).lower()


def test_feil_lar_den_ekte_loggen_staa(tmp_path):
    """Selv naar demoen stopper, skal filen vaere uroert."""
    v = filled(2)
    before = own_fingerprint(v.path)
    with pytest.raises(TamperDemoError):
        run_attack(ATTACK_ENDRE, path=v.path)
    assert own_fingerprint(v.path) == before


# ---------------------------------------------------------------------------
# at det er den EKSISTERENDE verifiseringen som svarer
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("attack", ATTACKS)
def test_svaret_kommer_fra_vault_store_sine_egne_tekster(attack):
    """Ingen ny, lettere sjekk: aarsak og tekst skal vaere vault/store.py sine."""
    v = filled(9)
    result = run_attack(attack, path=v.path)

    assert result.reason in VERIFY_TEXTS
    # Og teksten skal vaere den malen, ikke en omskrevet variant.
    mal = VERIFY_TEXTS[result.reason]
    fast_del = mal.split("{")[0].strip()
    assert fast_del and fast_del in result.verify_text


# ---------------------------------------------------------------------------
# linjen som velges
# ---------------------------------------------------------------------------


def test_angriperen_gaar_etter_en_roed_avgjoerelse_naar_det_finnes_en():
    v = filled(9)
    result = run_attack(ATTACK_ENDRE, path=v.path)
    assert "utfallet fra «rød» til «tillatt»" in result.what_we_did


def test_uten_noe_aa_foretrekke_sier_demoen_det_rett_ut():
    """En logg uten avgjørelser: vi later ikke som det stod et utfall der."""
    v = traps_only(7)
    result = run_attack(ATTACK_ENDRE, path=v.path)

    assert result.detected is True
    assert "la inn utfallet" in result.what_we_did
    assert "ikke hadde noe utfall" in result.what_we_did


def test_full_virker_ogsaa_paa_en_logg_med_bare_en_linje():
    v = filled(1)
    result = run_attack(ATTACK_FULL, path=v.path)
    assert result.detected is False
    assert result.lines_before == result.lines_after == 1
    assert own_fingerprint(v.path)["log"] is not None


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("attack", ATTACKS)
def test_cli_skriver_norsk_og_gaar_bra(attack, capsys):
    v = filled(9)
    assert main(["--attack", attack, "--path", str(v.path)]) == 0

    ut = capsys.readouterr().out
    assert "BRYT LOGGEN" in ut
    assert "den ekte loggen" in ut.lower()
    if ATTACK_EXPECT_DETECTED[attack]:
        assert "OPPDAGET" in ut
        assert "IKKE OPPDAGET" not in ut
    else:
        assert "IKKE OPPDAGET" in ut
        assert "ærlige svaret" in ut


def test_cli_alle_skriver_fire_bolker(capsys):
    v = filled(9)
    assert main(["--attack", "alle", "--path", str(v.path)]) == 0
    ut = capsys.readouterr().out
    assert ut.count("BRYT LOGGEN") == 4


def test_cli_json_kan_leses_av_et_endepunkt(capsys):
    v = filled(9)
    assert main(["--attack", ATTACK_KUTT, "--path", str(v.path), "--json"]) == 0

    body = json.loads(capsys.readouterr().out)
    assert body["attack"] == ATTACK_KUTT
    assert body["detected"] is True
    assert body["reason"] == "log_truncated"
    assert body["real_log_untouched"] is True


def test_cli_json_alle_gir_en_liste(capsys):
    v = filled(9)
    assert main(["--attack", "alle", "--path", str(v.path), "--json"]) == 0
    body = json.loads(capsys.readouterr().out)
    assert [item["attack"] for item in body] == list(ATTACKS)


def test_cli_feiler_lukket_med_exitkode_2(tmp_path, capsys):
    assert main(["--attack", ATTACK_ENDRE, "--path", str(tmp_path / "nei.jsonl")]) == 2
    feil = capsys.readouterr().err
    assert "Stoppet:" in feil
