"""Kjør: pytest -q  (fra rotmappen). Skal alltid være grønn før du slår sammen en gren."""

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from contracts import (
    GENESIS_HASH,
    ActionRequest,
    Decision,
    HumanResponse,
    LogEntry,
    make_log_entry,
    verify_chain,
)

EX = Path(__file__).resolve().parent.parent / "examples"


def load(name: str) -> dict:
    return json.loads((EX / name).read_text(encoding="utf-8"))


def test_examples_validate():
    ActionRequest(**load("request.json"))
    Decision(**load("decision.json"))
    HumanResponse(**load("human_response.json"))
    LogEntry(**load("log_entry.json"))


def test_wrong_field_name_fails_loudly():
    bad = load("request.json")
    bad["beløp"] = bad.pop("amount")
    with pytest.raises(ValidationError):
        ActionRequest(**bad)


def test_negative_amount_rejected():
    bad = load("request.json")
    bad["amount"] = -5
    with pytest.raises(ValidationError):
        ActionRequest(**bad)


def _chain(n: int = 4) -> list[LogEntry]:
    entries, prev = [], GENESIS_HASH
    for i in range(n):
        e = make_log_entry(i, datetime(2026, 11, 7, 10, 0, i, tzinfo=timezone.utc), "request", {"i": i}, prev)
        entries.append(e)
        prev = e.hash
    return entries


def test_chain_ok():
    assert verify_chain(_chain()) is None


def test_chain_detects_edit():
    entries = _chain()
    entries[2] = entries[2].model_copy(update={"payload": {"i": 999}})
    assert verify_chain(entries) == 2


def test_chain_detects_deleted_line():
    entries = _chain()
    del entries[1]
    assert verify_chain(entries) == 2
