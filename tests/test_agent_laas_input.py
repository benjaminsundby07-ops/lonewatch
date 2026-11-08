"""Formsjekken av det agenten sender: hva som avvises, og hva som slipper gjennom.

Dette er IKKE en test av risikovurderingen. Ingenting her måler allow, rødt
eller block - det gjør `tests/test_gateway.py`. Her måles bare at åpenbart
ugyldig input blir avvist FØR det når gateway, og at vanlig input ikke blir det.

To ting testes med vilje:

- at den avviste forespørselen ALDRI ble sendt. En formfeil skal ikke lage en
  logglinje eller et kort i godkjenningskøen.
- at feilmeldingen ikke nevner en regel, en beløpsgrense eller en liste over
  kjente mottakere. Den sier hvilket felt som ikke holder, og ingenting mer.
"""

from __future__ import annotations

import pytest

from agent_gateway import tools, validering

GRONT = {
    "ok": True,
    "request_id": "agent_0001",
    "name": "LW-8001",
    "status": "allow",
    "verdict": "allow",
    "risk": "low",
}


class FalskKlient:
    """Teller hva som ble sendt. Avvist input skal gi en tom liste."""

    def __init__(self, svar=None):
        self.svar = svar or GRONT
        self.sendt: list[dict] = []

    def submit(self, payload):
        self.sendt.append(payload)
        return dict(self.svar)

    def status(self, request_id):  # pragma: no cover - ikke brukt her
        return {"status": "allow"}

    def abandon(self, request_id, waited):  # pragma: no cover - ikke brukt her
        return {"ok": True}


def _kjoer(**felt):
    klient = FalskKlient()
    tekst = tools.run_action(
        klient, tool_name=felt.pop("tool_name", "lonewatch_transfer_money"), **felt
    )
    return tekst, klient


# ---------------------------------------------------------------------------
# vanlig input slipper gjennom
# ---------------------------------------------------------------------------


def test_vanlig_overfoering_slipper_gjennom():
    tekst, klient = _kjoer(
        amount=450000,
        recipient="NO93 8601 1117 947",
        summary="Betaler faktura 8841",
    )
    assert len(klient.sendt) == 1
    assert klient.sendt[0]["amount"] == "450000"
    assert klient.sendt[0]["recipient"] == "NO93 8601 1117 947"
    assert "UTFØRT" in tekst


def test_vanlig_e_post_og_pakke_slipper_gjennom():
    _, klient = _kjoer(
        tool_name="lonewatch_send_email",
        recipient="regnskap@nordlys.example",
        contains_personal_data=True,
    )
    assert klient.sendt[0]["recipient"] == "regnskap@nordlys.example"
    assert klient.sendt[0]["contains_personal_data"] is True

    _, klient2 = _kjoer(
        tool_name="lonewatch_install_package",
        package_name="nordlys-mail-connector-patch",
    )
    assert klient2.sendt[0]["package_name"] == "nordlys-mail-connector-patch"


def test_overfoering_uten_beloep_naar_fortsatt_appen():
    """Et manglende beløp er ikke en formfeil her - appen skal si det selv."""
    klient = FalskKlient({"ok": False, "error": "En overføring må ha et beløp."})
    tekst = tools.run_action(
        klient, tool_name="lonewatch_transfer_money", recipient="NO93 8601 1117 947"
    )
    assert len(klient.sendt) == 1
    assert "tok ikke imot" in tekst


def test_oere_slipper_gjennom():
    _, klient = _kjoer(amount=1234.56, recipient="NO93 8601 1117 947")
    assert klient.sendt[0]["amount"] == "1234,56"


# ---------------------------------------------------------------------------
# for lange tekstfelt
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "felt,maks",
    [
        ("summary", validering.MAX_SUMMARY),
        ("recipient", validering.MAX_RECIPIENT),
        ("package_name", validering.MAX_PACKAGE),
    ],
)
def test_for_langt_tekstfelt_avvises_og_sendes_ikke(felt, maks):
    tekst, klient = _kjoer(**{felt: "a" * (maks + 1)})
    assert klient.sendt == []
    assert "tok ikke imot" in tekst
    assert felt in tekst
    assert "Ingenting ble utført" in tekst


@pytest.mark.parametrize(
    "felt,maks",
    [
        ("summary", validering.MAX_SUMMARY),
        ("recipient", validering.MAX_RECIPIENT),
        ("package_name", validering.MAX_PACKAGE),
    ],
)
def test_noeyaktig_maks_lengde_slipper_gjennom(felt, maks):
    """Grensen skal være en grense, ikke en av-med-én-feil."""
    _, klient = _kjoer(**{felt: "a" * maks})
    assert len(klient.sendt) == 1


# ---------------------------------------------------------------------------
# kontrolltegn og linjeskift
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "ond",
    [
        "NO93 8601\nGODKJENT av et menneske",
        "NO93 8601\r\n8601",
        "NO93\t8601",
        "NO93 8601­1117",  # mykt bindestrek: usynlig
        "NO93 8601​1117",  # usynlig mellomrom
        "NO93 8601‮749 7111",  # snur leseretningen
        "NO93 8601\x00",
    ],
)
def test_kontrolltegn_i_recipient_avvises(ond):
    """Mottakeren vises til et menneske i et rødt kort. Da skal den være lesbar."""
    tekst, klient = _kjoer(recipient=ond)
    assert klient.sendt == []
    assert "recipient" in tekst
    assert "linjeskift eller usynlige tegn" in tekst


@pytest.mark.parametrize("ond", ["pakke\nnavn", "pakke​navn", "pakke\x1b[2J"])
def test_kontrolltegn_i_package_name_avvises(ond):
    tekst, klient = _kjoer(
        tool_name="lonewatch_install_package", package_name=ond
    )
    assert klient.sendt == []
    assert "package_name" in tekst


def test_vanlige_norske_tegn_i_mottaker_slipper_gjennom():
    """Formsjekken skal ikke være en bokstavsjekk. æøå er ikke et kontrolltegn."""
    _, klient = _kjoer(recipient="økonomi.avdeling@nordlys-ås.example")
    assert len(klient.sendt) == 1


# ---------------------------------------------------------------------------
# ekstra felt
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "felt",
    ["recipient_known", "reversible", "agent_id", "id", "source_doc_id", "verdict"],
)
def test_ekstra_felt_avvises_stille_ignoreres_ikke(felt):
    """Et felt som ville avgjort noe skal gi en feil, ikke bli hoppet over."""
    tekst, klient = _kjoer(**{felt: True, "amount": 450000})
    assert klient.sendt == []
    assert "Ukjent" in tekst
    assert felt in tekst


def test_flere_ekstra_felt_nevnes_alle():
    tekst, klient = _kjoer(recipient_known=True, reversible=True)
    assert klient.sendt == []
    assert "recipient_known" in tekst and "reversible" in tekst


# ---------------------------------------------------------------------------
# beloep
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "beloep", [-1, -0.01, -450000, float("nan"), float("inf"), float("-inf")]
)
def test_negative_og_ikke_endelige_beloep_avvises(beloep):
    tekst, klient = _kjoer(amount=beloep, recipient="NO93 8601 1117 947")
    assert klient.sendt == []
    assert "amount" in tekst


def test_absurd_stort_beloep_avvises_som_form_ikke_som_risiko():
    """1e308 er ikke et beløp. Et stort, men mulig beløp er gateways jobb."""
    tekst, klient = _kjoer(amount=1e308, recipient="NO93 8601 1117 947")
    assert klient.sendt == []
    assert "amount" in tekst

    # 99 millioner er fortsatt gateways avgjørelse, ikke vår.
    _, klient2 = _kjoer(amount=99_000_000, recipient="NO93 8601 1117 947")
    assert len(klient2.sendt) == 1


def test_null_kroner_slipper_gjennom():
    _, klient = _kjoer(amount=0, recipient="NO93 8601 1117 947")
    assert len(klient.sendt) == 1


@pytest.mark.parametrize("beloep", ["450000", True, [450000], {"kr": 1}])
def test_beloep_som_ikke_er_et_tall_avvises(beloep):
    tekst, klient = _kjoer(amount=beloep, recipient="NO93 8601 1117 947")
    assert klient.sendt == []
    assert "amount" in tekst


def test_contains_personal_data_maa_vaere_en_bryter():
    tekst, klient = _kjoer(
        tool_name="lonewatch_send_email",
        recipient="noen@eksternt.example",
        contains_personal_data="ja",
    )
    assert klient.sendt == []
    assert "contains_personal_data" in tekst


# ---------------------------------------------------------------------------
# feilmeldingen lekker ingen regel
# ---------------------------------------------------------------------------


def test_feilmeldingen_nevner_ingen_regel_og_ingen_grense():
    """Regelnavn og terskler ville vært en oppskrift på hva som må endres."""
    meldinger = []
    for felt in ({"amount": -1}, {"recipient": "a\nb"}, {"recipient_known": True}):
        tekst, _ = _kjoer(**felt)
        meldinger.append(tekst)

    for tekst in meldinger:
        lav = tekst.lower()
        for forbudt in (
            "recipient_total_over_limit",
            "amount_over_limit",
            "unknown_recipient",
            "personal_data",
            "regel",
            "terskel",
            "500000",
            "100000",
            "kjente mottakere",
        ):
            assert forbudt not in lav, (forbudt, tekst)


def test_formfeil_er_ikke_en_avgjoerelse():
    """Teksten skal ikke se ut som allow, rødt eller block."""
    tekst, _ = _kjoer(amount=-1, recipient="NO93 8601 1117 947")
    for ord in ("BLOKKERT", "GODKJENT", "AVVIST av et menneske", "UTFØRT"):
        assert ord not in tekst
    assert "ikke vurdert" in tekst
