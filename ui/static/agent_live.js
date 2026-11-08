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
 *
 * CSS-en ligger ogsaa her, av samme grunn: style.css eies av en annen oekt.
 */

"use strict";

(() => {
  const POLL_MS = 1500;

  /* Merket paa kortet. Lagt inn herfra slik at style.css staar uroert. */
  const css = document.createElement("style");
  css.textContent = `
    .app-live {
      background: rgba(240, 145, 141, .16);
      color: var(--negative);
      border: 1px solid rgba(240, 145, 141, .35);
      border-radius: var(--radius-pill);
      padding: 1px var(--space-2);
      font-size: 11px;
      font-weight: 600;
    }
    .app-live-notis {
      position: fixed;
      left: 24px;
      bottom: 24px;
      max-width: 380px;
      z-index: 60;
      background: var(--panel, #171a21);
      border: 1px solid rgba(240, 145, 141, .35);
      border-left: 3px solid var(--negative);
      border-radius: 12px;
      padding: 14px 16px;
      box-shadow: 0 12px 32px rgba(0, 0, 0, .45);
      font-size: 13px;
      line-height: 19px;
      color: var(--ink-muted);
    }
    .app-live-notis b { display: block; color: var(--ink); margin-bottom: 4px; }
    .app-live-notis button {
      margin-top: 10px;
      background: none;
      border: 1px solid var(--line);
      color: var(--ink-muted);
      border-radius: var(--radius-pill);
      padding: 3px 12px;
      font: inherit;
      font-size: 12px;
      cursor: pointer;
    }
  `;
  document.head.appendChild(css);

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
      const res = await fetch("/api/state");
      if (!res.ok) throw new Error(String(res.status));
      state = await res.json();
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
    document.body.appendChild(ny);
  }

  const timer = setInterval(tikk, POLL_MS);
})();
