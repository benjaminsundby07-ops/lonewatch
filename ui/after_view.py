"""«Etter»-listen slik et menneske skal lese den.

`vault/after.py` lager oppgavene. Den eier hva som skal følges opp, og den
leser bare logglinjer — den er riktig som den er.

Denne filen eier noe annet: hvordan det ser ut for den som skal gjøre jobben.
Tre ting manglet i visningen, og alle tre er presentasjon:

1. **Gruppering.** `req_0021` fikk to kort fordi den utløste to oppgaver. Et
   menneske ser én hendelse, ikke to.
2. **Rekkefølge.** Atten like kort uten prioritet er en liste, ikke en
   arbeidsordre. Det som haster skal stå først.
3. **Norsk, og noe å kjenne igjen.** Rollene het `security` og `finance`, og
   `req_0006` var eneste identifikator. Nå står agent, handling og beløp først,
   og IDen står lite ved siden av.

Teksten bygges her, fra de samme logglinjene — ikke ved å lappe på strengene
`vault/after.py` har laget. Det betyr at `/api/after` sine rå `items` fortsatt
har de gamle formuleringene for den som leser API-et direkte.
"""

from __future__ import annotations

from typing import Any, Iterable

# Hvor mye noe haster. Lavest tall først.
HASTER = 0
VIKTIG = 1
NAAR_DU_FAAR_TID = 2

PRIORITET_NAVN: dict[int, str] = {
    HASTER: "Haster",
    VIKTIG: "Viktig",
    NAAR_DU_FAAR_TID: "Når du får tid",
}

# Norske navn på hvem som eier oppgaven. `vault/after.py` bruker engelske
# kodenavn, og de skal ikke stå på skjermen.
ROLLE_NAVN: dict[str, str] = {
    "security": "Sikkerhet",
    "finance": "Økonomi",
    "employee": "Den ansatte",
    "it": "IT",
}

HANDLING_NAVN: dict[str, str] = {
    "send_email": "Sender e-post",
    "transfer_money": "Overfører penger",
    "share_data": "Deler data",
    "install_package": "Installerer tillegg",
    "read_document": "Leser dokument",
    "update_calendar": "Oppdaterer kalender",
}

AGENT_NAVN: dict[str, str] = {
    "customer_service": "Kundeservice",
    "procurement": "Innkjøp",
    "finance": "Økonomi",
    "hr": "HR",
    "it_helper": "IT-hjelp",
    "jury": "Juryen",
}


def _rolle(kode: str) -> str:
    return ROLLE_NAVN.get(kode, kode)


def _agent(kode: str) -> str:
    return AGENT_NAVN.get(kode, kode)


def _belop(verdi: Any) -> str | None:
    """10000000 -> '10 000 000 kr'. None hvis det ikke er et beløp."""
    if verdi is None:
        return None
    try:
        tall = float(verdi)
    except (TypeError, ValueError):
        return None
    hele, rest = divmod(int(round(tall * 100)), 100)
    ut = f"{hele:,}".replace(",", " ")
    if rest:
        ut = f"{ut},{rest:02d}"
    return f"{ut} kr"


def _rydd(tekst: str) -> str:
    """Fjerner dobbelt punktum og luft som oppstår når setninger settes sammen.

    «... at fella gikk av.. Fjern dokumentet» blir «... at fella gikk av.
    Fjern dokumentet».
    """
    ut = " ".join(str(tekst or "").split())
    while ".." in ut:
        ut = ut.replace("..", ".")
    return ut.strip()


def _overskrift(req: dict[str, Any], request_id: str) -> dict[str, Any]:
    """Det mennesket kjenner igjen: hvem, hva, hvor mye, til hvem.

    IDen er ikke borte - den står lite ved siden av, for den som skal slå opp
    i loggen. Den er bare ikke det eneste du har å gå på.
    """
    if not req:
        return {"agent": "Ukjent agent", "handling": "", "belop": None,
                "mottaker": None, "id": request_id}
    handling = str(req.get("action_type") or "")
    return {
        "agent": _agent(str(req.get("agent_id") or "")),
        "handling": HANDLING_NAVN.get(handling, handling),
        "belop": _belop(req.get("amount")),
        "mottaker": req.get("recipient") or None,
        "id": request_id,
    }


def _prioritet(kind: str, payload: dict[str, Any], req: dict[str, Any]) -> int:
    """Hvor mye det haster, utledet av hva som faktisk skjedde.

    Fast regel, ingen skjønn: en felle som gikk av og et tillegg som ble
    stoppet må noen se på nå. En rød overføring venter allerede på et menneske
    i køen. En godkjenning som bør kontrolleres i ettertid kan vente.
    """
    if kind == "trap":
        return HASTER
    if kind == "sandbox":
        return HASTER if payload.get("verdict") != "clean" else NAAR_DU_FAAR_TID
    if kind == "decision":
        if payload.get("verdict") == "block":
            return HASTER
        return VIKTIG
    if kind == "human":
        return NAAR_DU_FAAR_TID
    return VIKTIG


def _oppgaver(kind: str, payload: dict[str, Any], req: dict[str, Any]) -> list[dict[str, str]]:
    """Hva som faktisk må gjøres. Én linje per ting, på norsk."""
    if kind == "trap":
        doc = payload.get("doc_id", "ukjent dokument")
        agent = _agent(str(payload.get("agent_id") or ""))
        # Samme felle kan gå av flere ganger for samme agent og dokument. Da
        # hører alle i samme sak, og hvem og hvilket dokument står allerede i
        # overskriften. Gjentar vi innledningen per gang, blir saken et vegg
        # av nesten lik tekst og det som faktisk skiller dem forsvinner.
        return [
            {
                "rolle": "security",
                "tekst": _rydd(
                    f"{payload.get('what_happened', '')} "
                    f"Fjern dokumentet og finn ut hvem som la det inn."
                ),
            },
            {
                "rolle": "employee",
                "tekst": (
                    f"Bytt nøkler og passord {agent} hadde tilgang til. "
                    f"Dokumentet var {doc}."
                ),
            },
        ]

    if kind == "sandbox":
        navn = payload.get("package_name", "ukjent tillegg")
        if payload.get("attempted_network"):
            mål = ", ".join(str(d) for d in (payload.get("destinations") or []))
            return [{
                "rolle": "security",
                # Samme tillegg kan kjøres flere ganger, og adressene kan være
                # maskert i den ene linjen og ikke i den andre. Da er teksten
                # forskjellig, men jobben er den samme - én oppgave, ikke to.
                "nøkkel": f"sandkasse:{navn}:nettverk",
                "tekst": _rydd(
                    f"Tillegget «{navn}» ble kjørt i den lukkede boksen og forsøkte å "
                    f"kontakte {mål or 'et ukjent sted'}. Sandkassen svarte nei, så "
                    "ingenting forlot maskinen. Blokker adressene og se etter samme "
                    "forsøk i ekte logger."
                ),
            }]
        if payload.get("verdict") == "blocked":
            return [{
                "rolle": "security",
                "nøkkel": f"sandkasse:{navn}:blokkert",
                "tekst": _rydd(
                    f"Tillegget «{navn}» ble stoppet i den lukkede boksen uten at det "
                    "forsøkte nettverk. Les notatet på sandkasselinjen i loggen."
                ),
            }]
        if payload.get("verdict") == "not_tested":
            return [{
                "rolle": "security",
                "nøkkel": f"sandkasse:{navn}:ikke-testet",
                "tekst": _rydd(
                    f"Sandkassen fikk ikke testet tillegget «{navn}»: det kom aldri i "
                    "gang. Vi vet ikke hva det ville gjort."
                ),
            }]
        return []

    if kind == "decision":
        verdict = payload.get("verdict")
        ut: list[dict[str, str]] = []
        handling = str(req.get("action_type") or "")
        if verdict == "block" and handling == "install_package":
            ut.append({
                "rolle": "security",
                "tekst": _rydd(
                    f"Tillegget «{req.get('package_name') or 'ukjent'}» ble blokkert. "
                    "Sjekk om det er forsøkt installert andre steder, og hvem som ba "
                    "om det."
                ),
            })
        if verdict == "red" and handling == "transfer_money":
            ut.append({
                "rolle": "finance",
                "tekst": _rydd(
                    "Overføringen ble stoppet for menneskelig godkjenning. Bekreft "
                    "med mottaker gjennom en annen kanal før noe utbetales."
                ),
            })
        if verdict in ("red", "block") and req.get("contains_personal_data"):
            ut.append({
                "rolle": "security",
                "tekst": _rydd(
                    "Personopplysninger var på vei ut av huset. Vurder om dette er "
                    "et avvik som skal meldes."
                ),
            })
        return ut

    if kind == "human" and payload.get("approved") is True:
        sekunder = payload.get("seconds_to_decide")
        tid = f" etter {round(float(sekunder))} sekunder" if sekunder is not None else ""
        return [{
            "rolle": "security",
            "tekst": _rydd(
                f"{payload.get('employee_pseudonym', 'En ansatt')} godkjente den "
                f"røde forespørselen{tid}. Kontroller i ettertid at godkjenningen "
                "var riktig."
            ),
        }]

    return []


def build_after_view(entries: Iterable[Any]) -> dict[str, Any]:
    """Grupperte, prioriterte oppfølginger - én boks per forespørsel.

    Bygges fra logglinjene, akkurat som `vault.after.build_after_actions()`.
    Forskjellen er at denne svarer på «hva skal jeg gjøre nå», ikke «hva skjedde».
    """
    entries = list(entries)

    # Forespørslene, slik at en oppgave kan vise hvem og hva den gjelder.
    requests: dict[str, dict[str, Any]] = {}
    for e in entries:
        if e.kind == "request":
            rid = e.payload.get("id")
            if isinstance(rid, str):
                requests[rid] = e.payload

    grupper: dict[str, dict[str, Any]] = {}
    rekkefolge: list[str] = []

    for e in entries:
        payload = e.payload
        # Hvilken forespørsel hører linjen til? Sandkasse og feller har ingen
        # request_id, så de grupperes på det de faktisk gjelder.
        if e.kind == "request":
            continue
        if e.kind == "sandbox":
            nokkel = f"pakke:{payload.get('package_name')}"
            req = {}
        elif e.kind == "trap":
            nokkel = f"dok:{payload.get('doc_id')}:{payload.get('agent_id')}"
            req = {}
        else:
            nokkel = str(payload.get("request_id") or f"linje:{e.seq}")
            req = requests.get(nokkel, {})

        oppgaver = _oppgaver(e.kind, payload, req)
        if not oppgaver:
            continue

        prioritet = _prioritet(e.kind, payload, req)
        if nokkel not in grupper:
            rekkefolge.append(nokkel)
            if e.kind == "sandbox":
                topp = {"agent": "Sandkassen", "handling": "Testet et tillegg",
                        "belop": None, "mottaker": payload.get("package_name"),
                        "id": None}
            elif e.kind == "trap":
                topp = {"agent": _agent(str(payload.get("agent_id") or "")),
                        "handling": "Leste et dokument med felle", "belop": None,
                        "mottaker": payload.get("doc_id"), "id": None}
            else:
                topp = _overskrift(req, nokkel)
            grupper[nokkel] = {
                "key": nokkel,
                "topp": topp,
                "prioritet": prioritet,
                "oppgaver": [],
                "roller": [],
                "sett": set(),
            }

        gruppe = grupper[nokkel]
        gruppe["prioritet"] = min(gruppe["prioritet"], prioritet)
        for o in oppgaver:
            # To linjer er samme oppgave hvis de har samme nøkkel, eller - når
            # ingen nøkkel er satt - nøyaktig samme tekst.
            egen = o.pop("nøkkel", None) or o["tekst"]
            if egen in gruppe["sett"]:
                continue
            gruppe["sett"].add(egen)
            gruppe["oppgaver"].append(o)
            rolle = _rolle(o["rolle"])
            if rolle not in gruppe["roller"]:
                gruppe["roller"].append(rolle)

    # Stabil rekkefølge: det som haster først, ellers slik det skjedde.
    saker = sorted(
        (grupper[k] for k in rekkefolge),
        key=lambda g: (g["prioritet"], rekkefolge.index(g["key"])),
    )

    for sak in saker:
        sak.pop("sett", None)

    bolker = []
    for nivaa in (HASTER, VIKTIG, NAAR_DU_FAAR_TID):
        i_bolken = [s for s in saker if s["prioritet"] == nivaa]
        if i_bolken:
            bolker.append({
                "nivaa": nivaa,
                "navn": PRIORITET_NAVN[nivaa],
                "saker": i_bolken,
            })

    return {
        "bolker": bolker,
        "antall": len(saker),
        "antall_oppgaver": sum(len(s["oppgaver"]) for s in saker),
    }
