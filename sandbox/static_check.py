"""Les kilden til et tillegg FØR den kjøres, og si nei til kjente rømningsveier.

Dette er en deterministisk sjekk på et AST. Ingen AI, ingen heuristikk på
tilleggets egen beskrivelse av seg selv, ingen tilfeldighet: samme kilde gir
samme svar hver gang.

Hvorfor den finnes: sperrene i `sandbox/harness.py` er vanlige Python-funksjoner
i SAMME prosess som tillegget. Et tillegg som får tak i funksjonsobjektene -
`open.__globals__`, `(0).__class__.__mro__`, `type.__subclasses__()` - står
utenfor sperrene uten å utløse en eneste av dem, og boksen så før dette
ingenting og sa `clean`. Den eneste måten å se den veien i samme prosess er å
nekte mønsteret før koden får kjøre.

Hva sjekken IKKE er:

- Den er ikke et bevis på at kilden er trygg. Den avviser MØNSTRE vi kjenner.
  `"__glob" + "als__"` satt sammen under kjøringen, et navn hentet fra en fil
  eller en streng dekodet fra base64 går rett gjennom.
- Den gjør ikke sandkassen til en ekte sandkasse. Python-isolasjon i samme
  prosess kan ikke gjøres sikker. Se `sandbox/LIMITS.md`.

Bruk:

    findings = check_source(source)
    if findings:
        ...  # tillegget kjøres ikke, rapporten blir `blocked`
"""

from __future__ import annotations

import ast
from dataclasses import dataclass

# Attributter som gir tilgang til maskineriet under Python, og dermed til
# funksjonsobjektene sperrene våre er. Alle seks i oppdraget står her, pluss
# noen naboer som gir nøyaktig samme vei inn.
DENIED_ATTRIBUTES: frozenset[str] = frozenset({
    # de seks fra oppdraget
    "__globals__",
    "__builtins__",
    "__subclasses__",
    "__class__",
    "__mro__",
    "__code__",
    # samme vei, andre dør
    "__bases__",
    "__base__",
    "__closure__",
    "__dict__",
    "__getattribute__",
    "__reduce__",
    "__reduce_ex__",
    "__init_subclass__",
    "__func__",
    "__self__",
    "__defaults__",
    "__kwdefaults__",
    "__wrapped__",
    # rammer og sporinger: samme ordbøker, bare en annen vei
    "f_globals",
    "f_locals",
    "f_back",
    "gi_frame",
    "cr_frame",
    "tb_frame",
    "_getframe",
})

# Navn som kjører tekst som kode, eller henter inn en modul uten å gå veien om
# `import` (som importsperren ser).
DENIED_NAMES: frozenset[str] = frozenset({"eval", "exec", "compile", "__import__"})

# Tillatt liste. `open` står her MED VILJE: hele poenget med boksen er å se et
# tillegg lese agnfilene, og `open` er byttet ut med en sperre som skriver ned
# hva som ble lest. Et tillegg som leser filer er ikke et tillegg som rømmer.
ALLOWED_NAMES: frozenset[str] = frozenset({"open"})

# Oppslag av attributt ved navn. `getattr(open, "__globals__")` omgår sjekken
# på attributtnavn, så kallet selv må avvises.
ATTRIBUTE_BY_NAME: frozenset[str] = frozenset({"getattr", "setattr", "delattr"})

# Moduler som HOLDER sperrene. Skriver tillegget til et attributt her, prøver
# det å bytte ut en sperre.
GUARD_MODULES: frozenset[str] = frozenset({
    "builtins",
    "io",
    "_io",
    "os",
    "posix",
    "nt",
    "socket",
    "_socket",
    "subprocess",
    "_posixsubprocess",
})


@dataclass(frozen=True)
class Finding:
    """Ett avvist mønster: regelen, hva som sto der, og hvilken linje."""

    rule: str
    detail: str
    lineno: int

    def text(self) -> str:
        return f"linje {self.lineno}: {self.detail} ({self.rule})"


def _denied_dunders_in(text: str) -> list[str]:
    """Hvilke sperrede attributtnavn som står som tekst i en streng."""
    return sorted(name for name in DENIED_ATTRIBUTES if name in text)


class _Walker(ast.NodeVisitor):
    def __init__(self) -> None:
        self.findings: list[Finding] = []

    def _add(self, rule: str, detail: str, node: ast.AST) -> None:
        self.findings.append(
            Finding(rule=rule, detail=detail, lineno=int(getattr(node, "lineno", 0)))
        )

    # -- attributter -----------------------------------------------------

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if node.attr in DENIED_ATTRIBUTES:
            self._add("dunder_attributt", f"tilgang til {node.attr}", node)
        self.generic_visit(node)

    # -- navn ------------------------------------------------------------

    def visit_Name(self, node: ast.Name) -> None:
        if node.id in DENIED_NAMES and node.id not in ALLOWED_NAMES:
            self._add("sperret_navn", f"bruk av {node.id}", node)
        self.generic_visit(node)

    # -- kall ------------------------------------------------------------

    def visit_Call(self, node: ast.Call) -> None:
        navn = node.func.id if isinstance(node.func, ast.Name) else None
        if navn in ATTRIBUTE_BY_NAME:
            arg = node.args[1] if len(node.args) >= 2 else None
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                self._add(
                    "getattr_med_streng",
                    f"{navn}(..., {arg.value!r}) henter et attributt ved navn",
                    node,
                )
            elif arg is not None:
                self._add(
                    "getattr_med_uttrykk",
                    f"{navn}(..., <uttrykk>) henter et attributt vi ikke kan lese her",
                    node,
                )
        self.generic_visit(node)

    # -- strenger --------------------------------------------------------

    def visit_Constant(self, node: ast.Constant) -> None:
        if isinstance(node.value, str):
            funnet = _denied_dunders_in(node.value)
            if funnet:
                self._add(
                    "dunder_i_streng",
                    "strengen nevner " + ", ".join(funnet),
                    node,
                )
        self.generic_visit(node)

    # -- skriving til sperrene -------------------------------------------

    def _check_target(self, target: ast.AST) -> None:
        if isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name):
            if target.value.id in GUARD_MODULES:
                self._add(
                    "sperre_overskriving",
                    f"skriver til {target.value.id}.{target.attr}",
                    target,
                )
        elif isinstance(target, (ast.Tuple, ast.List)):
            for element in target.elts:
                self._check_target(element)

    def visit_Assign(self, node: ast.Assign) -> None:
        for target in node.targets:
            self._check_target(target)
        self.generic_visit(node)

    def visit_AugAssign(self, node: ast.AugAssign) -> None:
        self._check_target(node.target)
        self.generic_visit(node)

    def visit_Delete(self, node: ast.Delete) -> None:
        for target in node.targets:
            self._check_target(target)
        self.generic_visit(node)


def check_source(source: str) -> list[Finding]:
    """Alle avviste mønstre i kilden. Tom liste betyr "ingen vi kjenner igjen".

    Kilde som ikke kan leses som Python er også et funn: da vet vi ikke hva den
    gjør, og da skal den ikke kjøres.
    """
    try:
        tree = ast.parse(source or "")
    except SyntaxError as exc:
        return [
            Finding(
                rule="kilden_kan_ikke_leses",
                detail=f"kilden er ikke gyldig Python: {exc.msg}",
                lineno=int(exc.lineno or 0),
            )
        ]
    walker = _Walker()
    walker.visit(tree)
    # Stabil rekkefølge: linje, så regel, så tekst. Samme kilde -> samme liste.
    return sorted(walker.findings, key=lambda f: (f.lineno, f.rule, f.detail))


def rules_in(findings: list[Finding]) -> list[str]:
    """Regelnavnene som slo til, uten duplikater, i stabil rekkefølge."""
    return sorted({f.rule for f in findings})
