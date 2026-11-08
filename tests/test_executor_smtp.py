"""SmtpExecutor og postfangeren. Eneste nettverk er localhost.

Ingen test her slaar opp et navn i DNS, og ingen test sender noe ut av
maskinen. Postfangeren binder seg til 127.0.0.1 paa en port operativsystemet
velger, slik at testene kan kjoere samtidig og uten internett.
"""

from __future__ import annotations

import smtplib
from datetime import datetime, timedelta, timezone

import pytest

from contracts import ActionRequest, ActionType, Decision, HumanResponse, Risk, Verdict
from executor import (
    ENV_ALLOW_REMOTE,
    ENV_FROM,
    ENV_HOST,
    ENV_PORT,
    ENV_STARTTLS,
    ENV_TIMEOUT,
    ExecutionStatus,
    MailCatcher,
    SmtpConfig,
    SmtpExecutor,
    build_message,
    is_local,
    mask_address,
    seal,
    subject_from,
    valid_address,
)

TS = datetime(2026, 11, 8, 9, 0, tzinfo=timezone.utc)
MOTTAKER = "oline.dahl@nordlys.no"


# ---------------------------------------------------------------------------
# byggeklosser
# ---------------------------------------------------------------------------


def epost(req_id: str = "req_1", recipient: str = MOTTAKER, **felt) -> ActionRequest:
    base = dict(
        id=req_id,
        ts=TS,
        agent_id="kundeservice",
        action_type=ActionType.SEND_EMAIL,
        summary="Svar paa sak 4411: skaden er registrert.",
        recipient=recipient,
    )
    base.update(felt)
    return ActionRequest(**base)


def avgjorelse(req: ActionRequest, verdict: Verdict = Verdict.ALLOW, risk: Risk = Risk.LOW) -> Decision:
    return Decision(
        request_id=req.id,
        ts=req.ts,
        verdict=verdict,
        risk=risk,
        reasons=["known_recipient"],
        consequence_text="E-posten sendes til en kjent mottaker.",
    )


def menneske(req_id: str, approved: bool = True) -> HumanResponse:
    return HumanResponse(
        request_id=req_id,
        ts=TS + timedelta(seconds=30),
        employee_pseudonym="emp_1a2b",
        approved=approved,
        seconds_to_decide=30.0,
    )


@pytest.fixture
def postfanger(tmp_path):
    """En postfanger paa loopback med en port operativsystemet velger."""
    with MailCatcher(directory=tmp_path / "maildrop") as catcher:
        yield catcher


@pytest.fixture
def utforer(postfanger):
    host, port = postfanger.address
    return SmtpExecutor(config=SmtpConfig(host=host, port=port))


# ---------------------------------------------------------------------------
# den ekte veien gjennom
# ---------------------------------------------------------------------------


def test_godkjent_epost_havner_som_eml_fil(postfanger, utforer):
    req = epost()
    dec = avgjorelse(req)
    res = utforer.execute(req, dec, seal(req, dec))

    assert res.executed is True
    assert res.status is ExecutionStatus.DONE

    filer = postfanger.eml_files()
    assert len(filer) == 1
    assert filer[0].suffix == ".eml"
    assert filer[0].read_text(encoding="utf-8").strip() != ""


def test_rod_sak_godkjent_av_et_menneske_sendes(postfanger, utforer):
    req = epost(recipient="ukjent@eksempel.invalid", recipient_known=False)
    dec = avgjorelse(req, Verdict.RED, Risk.HIGH)
    res = utforer.execute(req, dec, seal(req, dec, menneske(req.id)))

    assert res.executed is True
    assert len(postfanger.messages) == 1


@pytest.mark.parametrize(
    "verdict,svar,regel",
    [
        (Verdict.RED, None, "red_waiting"),
        (Verdict.RED, False, "red_rejected"),
        (Verdict.BLOCK, None, "verdict_block"),
        (Verdict.BLOCK, True, "verdict_block"),
    ],
    ids=["red-venter", "red-avvist", "block", "block-med-ja"],
)
def test_ingen_epost_forlater_maskinen_naar_porten_sier_nei(postfanger, utforer, verdict, svar, regel):
    req = epost()
    dec = avgjorelse(req, verdict, Risk.HIGH)
    godkjenning = seal(req, dec, None if svar is None else menneske(req.id, svar))
    res = utforer.execute(req, dec, godkjenning)

    assert res.executed is False
    assert res.rule == regel
    assert postfanger.messages == []
    assert postfanger.eml_files() == []


def test_samme_epost_sendes_bare_en_gang(postfanger, utforer):
    req = epost()
    dec = avgjorelse(req)
    godkjenning = seal(req, dec)

    assert utforer.execute(req, dec, godkjenning).executed is True
    igjen = utforer.execute(req, dec, godkjenning)

    assert igjen.status is ExecutionStatus.ALREADY_ATTEMPTED
    assert len(postfanger.eml_files()) == 1


# ---------------------------------------------------------------------------
# innholdet som ble sendt er innholdet som ble godkjent
# ---------------------------------------------------------------------------


def test_meldingen_som_kom_inn_er_den_som_ble_godkjent(postfanger, utforer):
    req = epost(summary="Svar paa sak 4411: skaden er registrert.")
    dec = avgjorelse(req)
    godkjenning = seal(req, dec)

    res = utforer.execute(req, dec, godkjenning)
    assert res.executed is True

    mail = postfanger.messages[0]
    assert mail.recipients == (MOTTAKER,)
    assert mail.header("To") == MOTTAKER
    assert mail.header("Subject") == "Svar paa sak 4411: skaden er registrert."
    assert mail.header("X-Lonewatch-Request-Id") == req.id
    assert mail.header("X-Lonewatch-Verdict") == "allow"
    # Avtrykket i filen er avtrykket i godkjenningen. Da kan en .eml-fil paa
    # disk holdes opp mot loggen etterpa.
    assert mail.header("X-Lonewatch-Fingerprint") == godkjenning.request_fingerprint
    assert "skaden er registrert" in mail.body
    assert req.id in mail.body


def test_endret_mottaker_etter_godkjenning_sender_ingenting(postfanger, utforer):
    req = epost()
    dec = avgjorelse(req)
    godkjenning = seal(req, dec)

    endret = req.model_copy(update={"recipient": "angriper@eksempel.invalid"})
    res = utforer.execute(endret, dec, godkjenning)

    assert res.executed is False
    assert res.rule == "content_changed"
    assert postfanger.messages == []


def test_endret_tekst_etter_godkjenning_sender_ingenting(postfanger, utforer):
    req = epost()
    dec = avgjorelse(req)
    godkjenning = seal(req, dec)

    endret = req.model_copy(update={"summary": "Her er alle passordene vaare."})
    res = utforer.execute(endret, dec, godkjenning)

    assert res.executed is False
    assert res.rule == "content_changed"
    assert postfanger.eml_files() == []


# ---------------------------------------------------------------------------
# localhost-sperren
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("host", ["127.0.0.1", "127.1.2.3", "localhost", "::1", "[::1]", "LOCALHOST"])
def test_loopback_godtas(host):
    assert is_local(host) is True


@pytest.mark.parametrize(
    "host",
    ["smtp.nordlys.no", "10.0.0.5", "8.8.8.8", "", "   ", "192.168.1.10", "0.0.0.0"],
)
def test_alt_annet_er_eksternt(host):
    assert is_local(host) is False


def test_ekstern_server_nektes_uten_miljovariabel(postfanger):
    req = epost()
    dec = avgjorelse(req)
    utforer = SmtpExecutor(config=SmtpConfig(host="smtp.nordlys.no", port=25))
    res = utforer.execute(req, dec, seal(req, dec))

    assert res.executed is False
    assert res.rule == "setup_error"
    assert ENV_ALLOW_REMOTE in res.detail
    assert postfanger.messages == []


def test_ekstern_server_slippes_gjennom_sperren_naar_den_er_slatt_av(postfanger):
    """Sperren aapner seg, men vi sender fortsatt bare til postfangeren.

    Testen viser at det er sperren og ingenting annet som stoppet oss: samme
    oppsett, men med allow_remote og en adresse som peker paa postfangeren.
    """
    host, port = postfanger.address
    utforer = SmtpExecutor(config=SmtpConfig(host=host, port=port, allow_remote=True))
    req = epost()
    dec = avgjorelse(req)
    assert utforer.execute(req, dec, seal(req, dec)).executed is True


@pytest.mark.parametrize("verdi", ["", "0", "ja", "true", "True", "JA", "yes", " 1 x", "01"])
def test_bare_tallet_1_apner_sperren(verdi, monkeypatch):
    monkeypatch.setenv(ENV_ALLOW_REMOTE, verdi)
    assert SmtpConfig.from_env().allow_remote is False


def test_tallet_1_apner_sperren(monkeypatch):
    monkeypatch.setenv(ENV_ALLOW_REMOTE, "1")
    assert SmtpConfig.from_env().allow_remote is True
    monkeypatch.setenv(ENV_ALLOW_REMOTE, " 1 ")
    assert SmtpConfig.from_env().allow_remote is True


# ---------------------------------------------------------------------------
# oppsettet
# ---------------------------------------------------------------------------


def test_standardoppsettet_peker_paa_denne_maskinen(monkeypatch):
    for navn in (ENV_HOST, ENV_PORT, ENV_FROM, ENV_TIMEOUT, ENV_ALLOW_REMOTE, ENV_STARTTLS):
        monkeypatch.delenv(navn, raising=False)
    config = SmtpConfig.from_env()

    assert is_local(config.host) is True
    assert config.allow_remote is False
    assert config.starttls is False
    assert config.port == 8025


def test_oppsettet_leses_fra_miljoet(monkeypatch):
    monkeypatch.setenv(ENV_HOST, "127.0.0.1")
    monkeypatch.setenv(ENV_PORT, "2525")
    monkeypatch.setenv(ENV_FROM, "agent@nordlys.no")
    monkeypatch.setenv(ENV_TIMEOUT, "3.5")
    config = SmtpConfig.from_env()

    assert (config.host, config.port, config.sender, config.timeout_s) == (
        "127.0.0.1",
        2525,
        "agent@nordlys.no",
        3.5,
    )


@pytest.mark.parametrize(
    "miljo",
    [
        {ENV_PORT: "ikke-et-tall"},
        {ENV_PORT: "0"},
        {ENV_PORT: "70000"},
        {ENV_PORT: "-1"},
        {ENV_TIMEOUT: "nei"},
        {ENV_TIMEOUT: "0"},
        {ENV_TIMEOUT: "9999"},
        {ENV_HOST: "bruker:passord@smtp.nordlys.no"},
        {ENV_HOST: "127.0.0.1:25"},
        {ENV_HOST: "smtp.nordlys.no/noe"},
    ],
    ids=[
        "port-tekst", "port-null", "port-for-stor", "port-negativ",
        "tid-tekst", "tid-null", "tid-for-lang",
        "vert-med-passord", "vert-med-port", "vert-med-sti",
    ],
)
def test_daarlig_oppsett_blir_ikke_utfort_i_stedet_for_en_krasj(miljo, monkeypatch, postfanger):
    for navn, verdi in miljo.items():
        monkeypatch.setenv(navn, verdi)

    req = epost()
    dec = avgjorelse(req)
    res = SmtpExecutor().execute(req, dec, seal(req, dec))

    assert res.executed is False
    assert res.rule == "setup_error"
    assert postfanger.messages == []


def test_tom_miljovariabel_betyr_bruk_standarden(monkeypatch):
    """Tom verdi er det samme som ikke satt. Samme regel som i vault."""
    monkeypatch.setenv(ENV_HOST, "")
    monkeypatch.setenv(ENV_PORT, "")
    monkeypatch.setenv(ENV_TIMEOUT, "")
    config = SmtpConfig.from_env()

    assert is_local(config.host) is True
    assert config.port == 8025
    assert config.allow_remote is False


def test_en_vert_med_passord_i_den_havner_ikke_i_svaret(monkeypatch, postfanger):
    monkeypatch.setenv(ENV_HOST, "bruker:hemmelig@smtp.nordlys.no")
    req = epost()
    dec = avgjorelse(req)
    res = SmtpExecutor().execute(req, dec, seal(req, dec))

    assert "hemmelig" not in res.detail
    assert res.executed is False


# ---------------------------------------------------------------------------
# adresser
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "adresse",
    ["a@b.no", "oline.dahl@nordlys.no", "navn+merke@under.nordlys.no", "x@eksempel.invalid"],
)
def test_gyldige_adresser(adresse):
    assert valid_address(adresse) is True


@pytest.mark.parametrize(
    "adresse",
    [
        None,
        "",
        "ingen-krok",
        "to@krok@er.no",
        "uten-toppdomene@localhost",
        "a@b",
        "a@.no",
        "med mellomrom@b.no",
        "a@b.no, en-annen@c.no",
        "a@b.no\nBcc: skjult@c.no",
        "a@b.no\r\nSubject: noe annet",
        "<a@b.no>",
        "a" * 300 + "@b.no",
    ],
    ids=[
        "none", "tom", "ingen-krok", "to-kroker", "localhost", "uten-punktum",
        "tomt-domene", "mellomrom", "komma", "linjeskift", "crlf",
        "vinkelparenteser", "for-lang",
    ],
)
def test_ugyldige_adresser(adresse):
    assert valid_address(adresse) is False


def test_ugyldig_mottaker_sender_ingenting(postfanger, utforer):
    req = epost(recipient="ikke-en-adresse")
    dec = avgjorelse(req)
    res = utforer.execute(req, dec, seal(req, dec))

    assert res.executed is False
    assert res.rule == "setup_error"
    assert postfanger.messages == []


def test_mottaker_uten_adresse_sender_ingenting(postfanger, utforer):
    req = epost(recipient=None)
    dec = avgjorelse(req)
    res = utforer.execute(req, dec, seal(req, dec))

    assert res.executed is False
    assert postfanger.messages == []


def test_adressen_maskeres_i_svaret(postfanger, utforer):
    req = epost()
    dec = avgjorelse(req)
    res = utforer.execute(req, dec, seal(req, dec))

    assert res.executed is True
    assert MOTTAKER not in res.detail
    assert "o***@nordlys.no" in res.detail


@pytest.mark.parametrize(
    "inn,ut",
    [
        ("oline.dahl@nordlys.no", "o***@nordlys.no"),
        ("a@b.no", "a***@b.no"),
        ("@b.no", "***@b.no"),
        ("", "ukjent mottaker"),
        (None, "ukjent mottaker"),
        ("ingen-krok", "ukjent mottaker"),
    ],
)
def test_maskering(inn, ut):
    assert mask_address(inn) == ut


# ---------------------------------------------------------------------------
# bare send_email
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "action_type",
    [
        ActionType.TRANSFER_MONEY,
        ActionType.SHARE_DATA,
        ActionType.INSTALL_PACKAGE,
        ActionType.READ_DOCUMENT,
        ActionType.UPDATE_CALENDAR,
    ],
)
def test_andre_handlingstyper_gjores_ikke_av_smtp_utforeren(postfanger, utforer, action_type):
    req = ActionRequest(
        id="req_x",
        ts=TS,
        agent_id="okonomi",
        action_type=action_type,
        summary="Noe annet enn e-post.",
        recipient=MOTTAKER,
    )
    dec = avgjorelse(req)
    res = utforer.execute(req, dec, seal(req, dec))

    assert res.executed is False
    assert res.rule == "setup_error"
    assert postfanger.messages == []


# ---------------------------------------------------------------------------
# meldingen, uten nettverk
# ---------------------------------------------------------------------------


def test_emnet_er_forste_linje_av_agentens_tekst():
    req = epost(summary="Forste linje\nAndre linje")
    assert subject_from(req) == "Forste linje"


def test_tomt_emne_faar_en_standardtekst():
    assert subject_from(epost(summary="")) == "Melding fra en AI-agent"
    assert subject_from(epost(summary="   \n  ")) == "Melding fra en AI-agent"


def test_langt_emne_kuttes():
    emne = subject_from(epost(summary="a" * 400))
    assert len(emne) <= 120


def test_meldingen_har_ingen_maskinnavn_eller_tilfeldighet():
    """Samme forespoersel gir samme Message-ID. make_msgid() ville lagt inn
    vertsnavnet til maskinen som kjoerer demoen."""
    req = epost()
    dec = avgjorelse(req)
    en = build_message(req, dec, "lonewatch@lonewatch.invalid", fingerprint="abc")
    to = build_message(req, dec, "lonewatch@lonewatch.invalid", fingerprint="abc")

    assert en["Message-ID"] == to["Message-ID"]
    assert "lonewatch.invalid" in en["Message-ID"]


def test_konsekvensteksten_folger_med_i_meldingen():
    req = epost()
    dec = avgjorelse(req)
    msg = build_message(req, dec, "lonewatch@lonewatch.invalid")
    assert dec.consequence_text in msg.get_content()


# ---------------------------------------------------------------------------
# naar postserveren ikke er der
# ---------------------------------------------------------------------------


def test_server_som_ikke_svarer_gir_ikke_utfort(tmp_path):
    """En ledig port paa loopback. Ingen lytter der, saa kallet feiler."""
    import socket

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        ledig_port = s.getsockname()[1]

    req = epost()
    dec = avgjorelse(req)
    utforer = SmtpExecutor(config=SmtpConfig(host="127.0.0.1", port=ledig_port, timeout_s=2.0))
    res = utforer.execute(req, dec, seal(req, dec))

    assert res.executed is False
    assert res.status is ExecutionStatus.FAILED
    assert res.detail.startswith("Ikke utført")


def test_server_som_ikke_svarer_proves_ikke_igjen(postfanger):
    import socket

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        ledig_port = s.getsockname()[1]

    req = epost()
    dec = avgjorelse(req)
    godkjenning = seal(req, dec)
    utforer = SmtpExecutor(config=SmtpConfig(host="127.0.0.1", port=ledig_port, timeout_s=2.0))

    forst = utforer.execute(req, dec, godkjenning)
    assert forst.status is ExecutionStatus.FAILED

    # Samme utfoerer, men na peker den paa en server som VIRKER. Forespoerselen
    # skal fortsatt ikke sendes: vi vet ikke hva som skjedde forste gang.
    host, port = postfanger.address
    utforer._config = SmtpConfig(host=host, port=port)
    igjen = utforer.execute(req, dec, godkjenning)

    assert igjen.status is ExecutionStatus.ALREADY_ATTEMPTED
    assert postfanger.messages == []


# ---------------------------------------------------------------------------
# postfangeren selv
# ---------------------------------------------------------------------------


def test_postfangeren_binder_seg_bare_til_loopback(tmp_path):
    with pytest.raises(ValueError):
        MailCatcher(directory=tmp_path, host="0.0.0.0")
    with pytest.raises(ValueError):
        MailCatcher(directory=tmp_path, host="smtp.nordlys.no")


def test_postfangeren_tar_imot_flere_meldinger(postfanger):
    host, port = postfanger.address
    for n in range(3):
        with smtplib.SMTP(host, port, timeout=5, local_hostname="test.invalid") as smtp:
            smtp.sendmail("a@b.no", ["c@d.no"], f"Subject: nr {n}\r\n\r\nhei\r\n")

    assert len(postfanger.messages) == 3
    assert len(postfanger.eml_files()) == 3
    assert {m.path for m in postfanger.messages} == set(postfanger.eml_files())


def test_eml_filen_inneholder_det_som_ble_sendt(postfanger):
    host, port = postfanger.address
    with smtplib.SMTP(host, port, timeout=5, local_hostname="test.invalid") as smtp:
        smtp.sendmail("a@b.no", ["c@d.no"], "Subject: hei\r\n\r\nlinje en\r\nlinje to\r\n")

    tekst = postfanger.eml_files()[0].read_text(encoding="utf-8")
    assert "Subject: hei" in tekst
    assert "linje en" in tekst
    assert "linje to" in tekst


def test_konvolutten_holdes_utenfor_filen(postfanger):
    """.eml-filen er meldingen, ikke leveringen. Konvolutten ligger i minnet."""
    host, port = postfanger.address
    with smtplib.SMTP(host, port, timeout=5, local_hostname="test.invalid") as smtp:
        smtp.sendmail("avsender@b.no", ["mottaker@d.no"], "Subject: hei\r\n\r\nhei\r\n")

    mail = postfanger.messages[0]
    assert mail.envelope_from == "avsender@b.no"
    assert mail.recipients == ("mottaker@d.no",)
    assert "avsender@b.no" not in mail.raw


def test_punktum_paa_egen_linje_kommer_helt_frem(postfanger):
    """Punktum-stuffing: avsenderen dobler et ledende punktum, vi gjor det om igjen."""
    host, port = postfanger.address
    with smtplib.SMTP(host, port, timeout=5, local_hostname="test.invalid") as smtp:
        smtp.sendmail("a@b.no", ["c@d.no"], "Subject: hei\r\n\r\n.en linje som starter med punktum\r\n")

    assert ".en linje som starter med punktum" in postfanger.messages[0].raw


def test_postfangeren_nekter_data_uten_mottaker(postfanger):
    host, port = postfanger.address
    with smtplib.SMTP(host, port, timeout=5, local_hostname="test.invalid") as smtp:
        smtp.ehlo()
        smtp.mail("a@b.no")
        kode, _ = smtp.docmd("DATA")
    assert kode == 503
    assert postfanger.messages == []


def test_postfangeren_svarer_paa_noop_og_rset(postfanger):
    host, port = postfanger.address
    with smtplib.SMTP(host, port, timeout=5, local_hostname="test.invalid") as smtp:
        assert smtp.noop()[0] == 250
        assert smtp.rset()[0] == 250
        assert smtp.docmd("TULL")[0] == 502


def test_for_stor_melding_avvises_og_lagres_ikke(postfanger):
    from executor.mailcatcher import MAX_MESSAGE_BYTES

    host, port = postfanger.address
    stor = "x" * (MAX_MESSAGE_BYTES + 10_000)
    with smtplib.SMTP(host, port, timeout=20, local_hostname="test.invalid") as smtp:
        with pytest.raises(smtplib.SMTPDataError) as feil:
            smtp.sendmail("a@b.no", ["c@d.no"], f"Subject: stor\r\n\r\n{stor}\r\n")
    assert feil.value.smtp_code == 552
    assert postfanger.messages == []
    assert postfanger.eml_files() == []


def test_ingen_halve_eml_filer_ligger_igjen(postfanger, utforer):
    req = epost()
    dec = avgjorelse(req)
    utforer.execute(req, dec, seal(req, dec))

    assert list(postfanger.directory.glob("*.part")) == []
    assert len(postfanger.eml_files()) == 1


def test_postfangeren_kan_stoppes_og_startes_igjen(tmp_path):
    catcher = MailCatcher(directory=tmp_path / "post")
    catcher.start()
    host, port = catcher.address
    assert port > 0
    catcher.stop()

    # Ingen skal kunne koble seg til etter stopp.
    with pytest.raises(OSError):
        smtplib.SMTP(host, port, timeout=2, local_hostname="test.invalid")
