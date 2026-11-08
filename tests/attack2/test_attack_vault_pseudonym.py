"""Angrep 1b: pseudonymene.

To spoersmaal fra oppdraget:
  1. Kan et pseudonym reverseres eller gjettes fra kjente ansattnavn UTEN
     noekkelen?  -> HOLDER. HMAC-SHA256 med hemmelig noekkel kan ikke reverseres,
     og uten noekkelen kan ingen regne seg fram til pseudonymet til en kjent id.
  2. Er pseudonymet entydig?  -> HULL (dokumentert i vault/LIMITS.md punkt 5).
     4 hex = 65 536 muligheter. To ulike ansatte faar samme kode foer eller
     senere, og da staar to personers handlinger under samme pseudonym i loggen.

`reveal()` krever role == "admin", men rollen er bare en streng den som kaller
oppgir selv - det er ingen innlogging bak. Det testes ogsaa her.
"""

from __future__ import annotations

import hmac
from hashlib import sha256

import pytest

from vault.crypto import ENV_PSEUDONYM_KEY, new_pseudonym_key
from vault.identity import NotAuthorized, pseudonymize, reveal


# ---------------------------------------------------------------------------
# HOLDER: uten noekkelen kan et pseudonym verken reverseres eller gjettes.
# ---------------------------------------------------------------------------


def test_pseudonym_cannot_be_reproduced_without_the_key(monkeypatch):
    """Angriperen kjenner ansatt-id-en og pseudonymet, men ikke noekkelen.

    Han proever aa gjette seg fram med 2 000 egne noekler. Ingen av dem gir
    samme pseudonym som den ekte noekkelen - fordi det er en HMAC, ikke en hash
    av bare id-en.
    """
    real_key = new_pseudonym_key()
    monkeypatch.setenv(ENV_PSEUDONYM_KEY, real_key)
    target_id = "ansatt-007"
    target_pseudonym = pseudonymize(target_id)

    # Angriperen vet IKKE real_key. Han proever uten noekkel i det hele tatt:
    # en ren sha256 av id-en (den naive gjetningen) treffer ikke.
    naive = "emp_" + sha256(target_id.encode()).hexdigest()[:4]
    assert naive != target_pseudonym

    # Og 2 000 tilfeldige noekler treffer heller ikke systematisk: pseudonymet
    # henger paa EN bestemt hemmelig noekkel.
    hits = 0
    for _ in range(2000):
        guess_key = new_pseudonym_key().encode()
        guess = "emp_" + hmac.new(guess_key, target_id.encode(), sha256).hexdigest()[:4]
        if guess == target_pseudonym:
            hits += 1
    # Tilfeldige treff paa 16 bit skjer ~2000/65536 ~ 0.03 ganger; det er ikke
    # en reversering, det er bare bursdagsstoey. Poenget: uten den EKTE noekkelen
    # finnes det ingen vei fra id til pseudonym.
    assert hits <= 2


def test_same_employee_same_pseudonym_is_stable(monkeypatch):
    monkeypatch.setenv(ENV_PSEUDONYM_KEY, new_pseudonym_key())
    assert pseudonymize("ansatt-007") == pseudonymize("ansatt-007")


# ---------------------------------------------------------------------------
# HOLDER: reveal() avviser enhver rolle som ikke er "admin".
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("role", ["", "Admin", "ADMIN", "user", "security", "finance", "root"])
def test_reveal_refuses_non_admin_roles(monkeypatch, role):
    monkeypatch.setenv(ENV_PSEUDONYM_KEY, new_pseudonym_key())
    with pytest.raises(NotAuthorized):
        reveal("emp_0000", role)


def test_reveal_admin_on_empty_table_returns_none(monkeypatch):
    """Selv admin faar None naar personen ikke er registrert - ingen krasj, ingen lekkasje."""
    monkeypatch.setenv(ENV_PSEUDONYM_KEY, new_pseudonym_key())
    assert reveal("emp_dead", "admin") is None


# ---------------------------------------------------------------------------
# HULL (dokumentert, LIMITS punkt 5): kun 16 bit -> kollisjoner er uunngaaelige.
# ---------------------------------------------------------------------------


@pytest.mark.xfail(
    strict=True,
    reason=(
        "HULL: pseudonymet er 4 hex = 65 536 muligheter. To ULIKE ansatt-id-er "
        "faar samme pseudonym laenge foer et selskap er stort. Da staar to "
        "personers handlinger under samme kode i loggen, og en gransker kan "
        "ikke skille dem. Dette er dokumentert i vault/LIMITS.md punkt 5; "
        "testen gjoer det kjoerbart. Fiks: flere tegn (f.eks. 8-12 hex), eller "
        "en tabell som garanterer entydighet. Lav alvorlighet (personvern/"
        "sporbarhet), men det bryter loeftet om at loggen kan si HVEM."
    ),
)
def test_pseudonyms_are_unique(monkeypatch):
    """Paastanden 'ett pseudonym = én person' holder ikke: vi finner en kollisjon."""
    monkeypatch.setenv(ENV_PSEUDONYM_KEY, new_pseudonym_key())
    seen: dict[str, str] = {}
    for i in range(3000):
        eid = f"ansatt-{i:05d}"
        p = pseudonymize(eid)
        assert p not in seen, (
            f"kollisjon: {seen.get(p)} og {eid} deler {p} - men testen forventer "
            "entydighet, saa dette er hullet gjort synlig"
        )
        seen[p] = eid
