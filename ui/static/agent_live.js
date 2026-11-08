/* Lonewatch: live-oppdatering for den ekte agenten.
 *
 * Hvorfor en EGEN fil, og ikke noen linjer i app.js:
 * dette er et eksperiment paa egen gren, og app.js endres samtidig et annet
 * sted. Alt som hoerer til broen mot en ekte agent ligger derfor her, slik at
 * filen kan fjernes i sin helhet uten aa roere resten av nettsiden. Den har
 * ingen egen tilstand og ingen egne regler: den kaller `apply()` i app.js med
 * svaret fra /api/state, akkurat som den rolige stroemmen gjoer.
 *
 * Grunnen til at den maa finnes: et kall fra en agent kommer naar DEN vil, ikke
 * naar noen trykker paa noe. Uten denne filen staar et roedt kort i koeen uten
 * at skjermen viser det foer man laster siden paa nytt.
 */

"use strict";

(() => {
  const POLL_MS = 1500;

  /* CSS-en ligger i ui/static/style.css, sammen med resten av appens stiler.
   * Den sto en stund HER - lagt inn i <head> ved oppstart - fordi style.css
   * den gang var en annen oekts fil. Naa eies begge samme sted, og en side
   * som faar stilene sine injisert av et skript ser uferdig ut i det halve
   * sekundet foer skriptet kjoerer. Klassene er `.app-live` og
   * `.app-live-notis`. */


  /* Signaturen er det som faktisk betyr noe paa skjermen. Vi tegner bare om
   * naar den endrer seg, saa en side som staar stille ikke blinker. */
  function signatur(state) {
    const kort = []
      .concat(state.waiting || [], state.blocked || [], state.answered || [])
      .map((c) => c.request.id + ":" + c.status);
    return JSON.stringify([
      kort,
      (state.calm || []).length,
      state.calm_total,
      (state.notices || []).length,
      state.log && state.log.lines,
    ]);
  }

  /* Et menneske som skriver inn beloepet skal ikke bli avbrutt. Kortet tegnes
   * om med innerHTML, og da mister feltet markoeren. Vi venter til de er
   * ferdige - avgjoerelsen deres er viktigere enn at listen er helt fersk. */
  function noenSkriver() {
    const a = document.activeElement;
    return !!(a && a.getAttribute && a.getAttribute("data-amt"));
  }

  let feilPaaRad = 0;

  async function tikk() {
    if (document.hidden || noenSkriver()) return;
    let state;
    try {
      /* `api()` fra app.js, ikke en naken `fetch`.
       *
       * Den nakne `fetch`-en sendte ikke menneskenoekkelen, og /api/state
       * svarer BEGGE veier: den kom tilbake med det MINIMERTE snapshotet. Saa
       * ga `apply(state)` det videre som om det var hele saken, og en side
       * noen nettopp hadde laast opp falt tilbake til «Laast side» med maskert
       * mottaker - hvert andre sekund, uten at noen hadde logget ut.
       * Helper-en legger paa hodet naar noekkelen finnes. */
      state = typeof api === "function"
        ? await api("/api/state")
        : await (await fetch("/api/state")).json();
      feilPaaRad = 0;
    } catch (e) {
      /* Appen svarer ikke. Vi gir oss etter en stund i stedet for aa fylle
       * konsollen: siden viser fortsatt det den viste. */
      if (++feilPaaRad >= 20) clearInterval(timer);
      return;
    }
    /* Vi sammenligner mot det som faktisk STAAR paa skjermen (app.js sin
     * `latest`), ikke mot forrige runde her. Da kan vi ikke gaa glipp av en
     * endring som kom mellom to tikk. */
    visGaOpp(state);
    const vist = typeof latest !== "undefined" && latest ? signatur(latest) : null;
    if (signatur(state) === vist) return;
    if (typeof apply === "function") apply(state);
  }

  /* «Agenten sluttet aa vente». Notiser tegnes ikke noe annet sted i appen, og
   * uten dette ville den som sitter i dashbordet ikke se at agenten har gitt
   * opp - bare at kortet fortsatt staar der. Det staar INGENTING om dette i
   * loggen, og det skal det ikke: ingen HumanResponse har skjedd.
   * Se agent_gateway/LIMITS.md punkt 5. */
  let vistNotis = null;

  function visGaOpp(state) {
    /* `snapshot()` gir notisene NYESTE FOERST. */
    const siste = (state.notices || []).find((n) => n.kind === "agent") || null;
    const boks = document.getElementById("app-live-notis");
    if (!siste || siste.ts === vistNotis) return;
    vistNotis = siste.ts;
    if (boks) boks.remove();

    const ny = document.createElement("div");
    ny.id = "app-live-notis";
    ny.className = "app-live-notis";
    ny.setAttribute("role", "status");
    const tittel = document.createElement("b");
    tittel.textContent = siste.title || "Agenten sluttet å vente";
    const tekst = document.createElement("span");
    tekst.textContent = siste.detail || "";
    const lukk = document.createElement("button");
    lukk.type = "button";
    lukk.textContent = "Lukk";
    lukk.addEventListener("click", () => ny.remove());
    ny.append(tittel, tekst, lukk);
    /* Inne i `.lw`, ikke paa `document.body`. Designsystemets farger ligger
     * paa `.lw` og ikke paa `:root` (se tokens.css), saa en notis som henger
     * utenfor faar `var(--negative)` til aa slaa feil - og da forsvant den
     * roede kanten uten at noe feilet. */
    (document.querySelector(".lw") || document.body).appendChild(ny);
  }

  const timer = setInterval(tikk, POLL_MS);
})();
