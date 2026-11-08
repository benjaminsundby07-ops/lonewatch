"""Angrep 3: kapploep.

Send samme godkjenning og avvisning samtidig mot samme kort, og mange samtidige
/api/agent/submit. Kan et kort faa to utfall, havne to ganger i loggen, eller
gi en oedelagt kjede?

Runde en tok ikke noe ekte kapploep. Her gjoer vi det. Alt dette er DEFENSER vi
forventer at HOLDER: DemoState tar en RLock rundt baade respond() og submit, og
alle vault-skriv skjer under den samme laasen. Holder det, bestaar testene.
"""

from __future__ import annotations

import threading

import pytest

from attack_lib2 import AGENT_KEY, AGENT_KEY_HEADER, live_app


def _first_waiting(client):
    client.drain_feed()
    waiting = client.waiting()
    assert waiting, "ingen roede kort i demodataene"
    return waiting[0]


# ---------------------------------------------------------------------------
# HOLDER: samtidig godkjenn + avvis paa samme kort gir NOEYAKTIG ett utfall.
# ---------------------------------------------------------------------------


def test_simultaneous_approve_and_reject_yields_exactly_one_outcome(live_app):
    card = _first_waiting(live_app)
    rid = card["request"]["id"]
    expected_amount = card["request"].get("amount")
    needs_amount = card["decision"].get("requires_typed_amount")

    results: list[bool] = []
    lock = threading.Lock()
    barrier = threading.Barrier(20)

    def hammer(i: int) -> None:
        approve = i % 2 == 0
        body = {"request_id": rid, "approved": approve, "seconds_to_decide": 5.0}
        if approve and needs_amount:
            # Skriv beloepet noeyaktig som kortet viser det.
            body["typed_amount"] = str(expected_amount)
        barrier.wait()
        _, resp = live_app.post("/api/respond", body)
        if isinstance(resp, dict) and resp.get("ok"):
            with lock:
                results.append(resp["card"]["status"])

    threads = [threading.Thread(target=hammer, args=(i,)) for i in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # Noeyaktig ÉN skriving lyktes.
    assert len(results) == 1, f"kortet fikk {len(results)} utfall: {results}"
    assert results[0] in ("approved", "rejected")

    # Loggen stemmer fortsatt.
    _, verify = live_app.get("/api/verify")
    assert verify["ok"] is True


def test_double_approve_cannot_write_two_human_lines(live_app):
    card = _first_waiting(live_app)
    rid = card["request"]["id"]
    expected_amount = card["request"].get("amount")
    needs_amount = card["decision"].get("requires_typed_amount")
    body = {"request_id": rid, "approved": True, "seconds_to_decide": 3.0}
    if needs_amount:
        body["typed_amount"] = str(expected_amount)

    oks: list[bool] = []
    lock = threading.Lock()
    barrier = threading.Barrier(12)

    def hammer() -> None:
        barrier.wait()
        _, resp = live_app.post("/api/respond", dict(body))
        if isinstance(resp, dict) and resp.get("ok"):
            with lock:
                oks.append(True)

    threads = [threading.Thread(target=hammer) for _ in range(12)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(oks) == 1  # bare én godkjenning ble skrevet
    _, verify = live_app.get("/api/verify")
    assert verify["ok"] is True


# ---------------------------------------------------------------------------
# HOLDER: mange samtidige /api/agent/submit -> unike id-er, uoedelagt kjede.
# ---------------------------------------------------------------------------


def test_many_concurrent_agent_submits_keep_the_chain_intact(live_app):
    headers = {AGENT_KEY_HEADER: AGENT_KEY}
    ids: list[str] = []
    lock = threading.Lock()
    barrier = threading.Barrier(25)

    def submit(i: int) -> None:
        body = {
            "action_type": "transfer_money",
            "summary": f"samtidig {i}",
            "amount": "1000",
            "recipient": "NO11 2222 3333 441",
        }
        barrier.wait()
        _, resp = live_app.post("/api/agent/submit", body, headers=headers)
        if isinstance(resp, dict) and resp.get("request_id"):
            with lock:
                ids.append(resp["request_id"])

    threads = [threading.Thread(target=submit, args=(i,)) for i in range(25)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # Alle fikk svar, og id-ene er unike (ingen kollisjon under laasen).
    assert len(ids) == 25
    assert len(set(ids)) == 25, "to kort fikk samme id under kapploep"

    _, verify = live_app.get("/api/verify")
    assert verify["ok"] is True
