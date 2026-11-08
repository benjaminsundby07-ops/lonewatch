"""Tallene til dashbordet, regnet fra tilstanden og loggen.

Formen er den `design-handoff/DATASHAPE.md` beskriver, slik at svaret kan sendes
rett inn i `Lonewatch.setData(...)` uten mellomledd.

Regelen for hele denne filen: **vis bare tall vi faktisk har.** Mangler et tall,
settes feltet til `None`, og dashbordet viser «–». Det finnes ingen oppdiktede
prosenter, mål, snitt eller poengsummer her, og ingen kurve som ser ut som en
måling uten å være det.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from agents import scenarios

# Hvor mange punkter kurvene i de tre kortene har. Samme lengde som formen i
# designet, slik at kurven ser ut som den var tenkt.
CHART_BUCKETS = 14

# Hvor mange sirkler vi tegner på rød-kurven. Hver av dem er en ekte bøtte der
# det faktisk kom et rødt varsel.
MAX_MARKS = 3

# Engelske agentnavn. `scenarios.AGENT_LABELS` har bare norske, og datasettet
# skal ha begge språk selv om valget er skjult i UI.
AGENT_NAMES_EN: dict[str, str] = {
    "customer_service": "Customer service",
    "procurement": "Procurement",
    "finance": "Finance",
    "hr": "HR",
    "it_helper": "IT help",
    "jury": "The jury",
}

# All tekst, på begge språk. Hentet fra design-handoff/DATASHAPE.md.
#
# To endringer fra originalen, begge fordi originalen sa noe som ikke er sant:
#   nav[2]  "Under"/"During" -> "Godkjenning"/"Approval". Fanen heter det i appen.
#   range   "I dag"/"Today"  -> "Denne økten"/"This session". Det finnes ikke
#           noe tidsfilter, og tallene gjelder denne kjøringen, ikke et døgn.
TEXT: dict[str, dict[str, Any]] = {
    "no": {
        "exampleTag": "Eksempeldata",
        "nav": ["Oversikt", "Før", "Godkjenning", "Etter", "Prøv selv"],
        "alerts": "Varsler",
        "account": "Konto",
        "language": "Språk",
        "promoTitle": "Send din egen forespørsel",
        "promoText": (
            "Skriv en forespørsel og se den gå gjennom de samme reglene som "
            "demoen. Ingenting er avgjort på forhånd."
        ),
        "promoCta": "Prøv selv",
        "activity": "Agentaktivitet",
        "range": "Denne økten",
        "stats": ["Handlinger vurdert", "Røde varsler", "Blokkert"],
        "allowed": "Sluppet gjennom",
        "waiting": "Røde varsler som venter på menneske",
        "followed": "Fulgt opp",
        "of": "av",
        "table": "Agenter",
        "viewAll": "Se alle",
        "cols": ["Agent", "Handlinger", "Røde", "Blokkert", "Sluppet gjennom"],
        "logChain": "Loggkjede",
        "logChainSub": "Sjekk av logg",
        "lastChecked": "Sist sjekket:",
        "notChecked": "Ikke sjekket ennå",
        "status": {"ok": "OK", "broken": "Feil", "none": "–"},
        "sandboxRow": "Sandkasse",
        "logRow": "Logg",
        "sandboxStatus": "{tested} testet, {blocked} blokkert",
    },
    "en": {
        "exampleTag": "Example data",
        "nav": ["Overview", "Before", "Approval", "After", "Try it yourself"],
        "alerts": "Alerts",
        "account": "Account",
        "language": "Language",
        "promoTitle": "Send your own request",
        "promoText": (
            "Write a request and watch it go through the same rules as the demo. "
            "Nothing is decided in advance."
        ),
        "promoCta": "Try it yourself",
        "activity": "Agent activity",
        "range": "This session",
        "stats": ["Actions evaluated", "Red alerts", "Blocked"],
        "allowed": "Let through",
        "waiting": "Red alerts waiting for a human",
        "followed": "Followed up",
        "of": "of",
        "table": "Agents",
        "viewAll": "View all",
        "cols": ["Agent", "Actions", "Red", "Blocked", "Let through"],
        "logChain": "Log chain",
        "logChainSub": "Log check",
        "lastChecked": "Last checked:",
        "notChecked": "Not checked yet",
        "status": {"ok": "OK", "broken": "Broken", "none": "–"},
        "sandboxRow": "Sandbox",
        "logRow": "Log",
        "sandboxStatus": "{tested} tested, {blocked} blocked",
    },
}


def _parse_ts(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _buckets(cards: list[dict[str, Any]], buckets: int) -> list[list[dict[str, Any]]]:
    """Fordeler kortene på like store tidsbøtter mellom første og siste.

    Dette er et ekte forløp: hvert kort legges i bøtten tidsstempelet sitt
    hører hjemme i. Mangler tidsstempelet, havner kortet i siste bøtte - det er
    bedre enn å kaste det, og det er det nærmeste "nå".
    """
    out: list[list[dict[str, Any]]] = [[] for _ in range(buckets)]
    stamps = [_parse_ts(c["request"].get("ts")) for c in cards]
    kjente = [t for t in stamps if t is not None]
    if not kjente:
        for card in cards:
            out[-1].append(card)
        return out

    first, last = min(kjente), max(kjente)
    span = (last - first).total_seconds()
    for card, ts in zip(cards, stamps):
        if ts is None or span <= 0:
            index = buckets - 1 if ts is None else 0
        else:
            index = int((ts - first).total_seconds() / span * (buckets - 1))
        out[max(0, min(buckets - 1, index))].append(card)
    return out


def _series(cards: list[dict[str, Any]], buckets: int) -> dict[str, list[int]]:
    """Tre ekte serier over tid: vurderte, røde og blokkerte per bøtte."""
    fordelt = _buckets(cards, buckets)
    return {
        "evaluated": [len(b) for b in fordelt],
        "red": [len([c for c in b if c["decision"]["verdict"] == "red"]) for b in fordelt],
        "blocked": [len([c for c in b if c["decision"]["verdict"] == "block"]) for b in fordelt],
    }


def _chart_shapes(cards: list[dict[str, Any]], buckets: int) -> list[dict[str, Any]]:
    """Kurvene i de tre kortene, tegnet fra ekte tall.

    Ingen `ghost`: den svake kurven bak i designet hadde ingen ekte serie å
    være, og en pen kurve uten tall bak er en påstand vi ikke kan stå for.

    `marks` er bøtter der det faktisk kom et rødt varsel. DATASHAPE er tydelig
    på at en indeks utenfor `data` gjør at dashbordet ikke tegnes i det hele
    tatt, så de klippes mot lengden.
    """
    serier = _series(cards, buckets)
    red = serier["red"]
    marks = [i for i, n in enumerate(red) if n > 0][:MAX_MARKS]
    marks = [i for i in marks if 0 <= i < len(red)]
    return [
        {"data": serier["evaluated"]},
        {"data": red, "marks": marks},
        {"data": serier["blocked"]},
    ]


def _agents(cards: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Én rad per agent, i den rekkefølgen agentene dukket opp."""
    rekkefolge: list[str] = []
    per: dict[str, dict[str, int]] = {}
    for card in cards:
        agent_id = str(card["request"].get("agent_id") or "ukjent")
        if agent_id not in per:
            rekkefolge.append(agent_id)
            per[agent_id] = {"actions": 0, "red": 0, "blocked": 0, "allowed": 0}
        verdict = card["decision"]["verdict"]
        per[agent_id]["actions"] += 1
        if verdict == "red":
            per[agent_id]["red"] += 1
        elif verdict == "block":
            per[agent_id]["blocked"] += 1
        elif verdict == "allow":
            per[agent_id]["allowed"] += 1

    rader = []
    for agent_id in rekkefolge:
        norsk = scenarios.agent_label(agent_id)
        rader.append(
            {
                "id": agent_id,
                "name": {"no": norsk, "en": AGENT_NAMES_EN.get(agent_id, norsk)},
                **per[agent_id],
            }
        )
    return rader


def _log_chain(verify: dict[str, Any] | None) -> dict[str, Any]:
    """Ringen «Loggkjede». `None` til noen faktisk har sjekket loggen.

    Vi later ikke som den er OK før den er sjekket: `status: None` gir tom ring
    og teksten «Ikke sjekket ennå».
    """
    if not verify:
        return {"status": None, "checkedAt": None}
    return {
        "status": "ok" if verify.get("ok") else "broken",
        "checkedAt": verify.get("checked_at"),
    }


def build_overview(
    cards: list[dict[str, Any]],
    before: dict[str, Any] | None = None,
    verify: dict[str, Any] | None = None,
    log_error: str | None = None,
    log_lines: int | None = None,
    buckets: int = CHART_BUCKETS,
) -> dict[str, Any]:
    """Hele datasettet dashbordet tegner fra.

    `cards` er kortene slik `DemoState` har dem: ett per forespørsel som har
    vært gjennom mellomstasjonen, uansett om den kom fra demodataene,
    hendelsen eller «Prøv selv».

    `isExample` er alltid `False`. Alt her er regnet ut, ikke funnet på - og
    merkelappen «Eksempeldata» skal bare stå når tallene ikke er ekte.
    """
    before = before or {}
    statuser = [c["status"] for c in cards]
    verdicts = [c["decision"]["verdict"] for c in cards]

    waiting = statuser.count("waiting")
    # «Fulgt opp» er røde forespørsler et menneske faktisk har svart på.
    #
    # Ikke antall oppgaver i Etter-listen: `vault.after.build_after_actions()`
    # setter alltid `done=False`, og antallet oppgaver har ingen sammenheng med
    # nevneren `red`. «0 av 7» ville vært en gal brøk, ikke en måling.
    # Slik det er nå går regnestykket opp: waitingForHuman + followedUp == red.
    answered = statuser.count("approved") + statuser.count("rejected")

    return {
        "isExample": False,
        "defaultLang": "no",
        "counts": {
            "evaluated": len(cards),
            "red": verdicts.count("red"),
            "blocked": verdicts.count("block"),
            "allowed": verdicts.count("allow"),
            "waitingForHuman": waiting,
            "followedUp": answered,
        },
        "agents": _agents(cards),
        "logChain": _log_chain(verify),
        # "testet" er de vi FAKTISK fikk testet. Et tillegg som aldri kom i
        # gang (`not_tested`) telles ikke med - da ville tallet lovet mer enn
        # sandkassen gjorde.
        "sandbox": {
            "tested": before.get("clean", 0) + before.get("blocked", 0),
            "blocked": before.get("blocked"),
        },
        # Raden «Logg» er en annen opplysning enn ringen over: her spør vi om
        # loggen i det hele tatt kjører (nøkkel på plass, fil skrivbar), ikke om
        # kjeden stemmer. Begge er ekte, og de kan svare forskjellig.
        #
        # `lines` er antall linjer loggen faktisk har nå. Det er et tall, ikke
        # en status, og det er det eneste på Oversikt som sier hvor mye som
        # ligger i loggen. Står det «OK» alene, vet du ikke om det er OK for
        # null linjer eller for hundre.
        "log": {"status": "broken" if log_error else "ok", "lines": log_lines},
        "chartShapes": _chart_shapes(cards, buckets),
        "text": TEXT,
    }


def empty_overview(reason: str | None = None) -> dict[str, Any]:
    """Datasettet når vi ikke har tall å vise.

    Alt er `None`, som gir «–» overalt. Brukes når backend ikke kan svare.
    Eksempeltallene i `bundle.js` skal aldri vises som om de var ekte, så
    dette er det UI faller tilbake til - ikke den innebygde konstanten.
    """
    return {
        "isExample": False,
        "defaultLang": "no",
        "error": reason,
        "counts": {
            "evaluated": None,
            "red": None,
            "blocked": None,
            "allowed": None,
            "waitingForHuman": None,
            "followedUp": None,
        },
        "agents": [],
        "logChain": {"status": None, "checkedAt": None},
        "sandbox": {"tested": None, "blocked": None},
        "log": {"status": None, "lines": None},
        "chartShapes": [],
        "text": TEXT,
    }
