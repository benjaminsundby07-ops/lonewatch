/* Lonewatch. Ingen rammeverk, ingen byggesteg.
   Siden har ingen regler i seg: den viser det gateway og vault svarer. */

"use strict";

const FEED_MS = 2000;          // hvor ofte en harmløs forespørsel slippes gjennom
const STORY_SPEED = 1;         // 1 = hendelsen tar sine fulle 90 sekunder

const el = (id) => document.getElementById(id);
const esc = (s) =>
  String(s == null ? "" : s).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])
  );

/* Beloepsregelen kommer fra /static/amount.js, som er den samme regelen som
 * ui/amount.py. Ikke skriv en egen variant her. */
const amountMatches = (typed, expected) =>
  globalThis.LonewatchAmount.amountMatches(typed, expected);
const kroner = (n) =>
  n == null ? "" : Math.round(n).toLocaleString("nb-NO").replace(/ /g, " ") + " kr";

/* Norsk tekst for regelnavnene fra gateway. Ukjente navn vises som de er,
   slik at nye regler aldri blir usynlige. */
const RULE_TEXT = {
  unknown_recipient: "ukjent mottaker",
  amount_over_limit: "over beløpsgrensen",
  recipient_total_over_limit: "flere beløp til samme mottaker",
  irreversible: "kan ikke angres",
  personal_data_external: "personopplysninger ut av huset",
  new_package: "ukjent tillegg",
  destructive_change: "sletter eller overskriver, kan ikke angres",
  incomplete_request: "ufullstendig forespørsel",
  sandbox_blocked: "stoppet i sandkassen",
  package_on_blocklist: "tillegg på blokklisten",
  transfer_over_hard_limit: "over den harde grensen",
};

/* Visningsnavn avledet stabilt av IDen, slik skissene bruker LW-nummer.
 * Det er IKKE en ny identifikator: rå-IDen staar lite ved siden av overalt.
 * Prefikset skiller kildene saa to forespoersler aldri faar samme navn:
 *   req_0037 -> LW-1037   story_0004 -> LW-2004   custom_0001 -> LW-9001 */
function lwName(id) {
  const m = String(id || "").match(/^([a-z]+)_(\d+)$/);
  if (!m) return String(id || "");
  const serie = { req: 1, story: 2, agent: 8, custom: 9 }[m[1]];
  if (!serie) return String(id);
  return "LW-" + serie + String(m[2]).padStart(3, "0").slice(-3);
}

/* Alvorlighet finnes bare som Decision.risk (low/medium/high). Skissens
 * "92/100" og alvorlighet PER REGEL finnes ikke, og vi finner dem ikke paa. */
const RISK_TEXT = { high: "Høy", medium: "Middels", low: "Lav" };

const UTFALL_TEXT = {
  allow: "tillatt", red: "til menneske", block: "stoppet",
  trap: "felle", blocked: "blokkert", clean: "rent", not_tested: "ikke testet",
};

const VIEWS = [
  { tab: "overview", navn: "Oversikt", ikon: "home" },
  { tab: "before", navn: "Før", ikon: "shield" },
  { tab: "queue", navn: "Godkjenning", ikon: "alert" },
  { tab: "after", navn: "Etter", ikon: "check" },
  { tab: "custom", navn: "Prøv selv", ikon: "bars" },
];

let latest = null;
let waitingSig = null;   // hindrer at køen tegnes om mens noen skriver i den
let feedTimer = null;
let storyTimer = null;
let typed = {};          // request_id -> det brukeren har skrevet
let shownAt = {};        // request_id -> når kortet kom på skjermen
let activeTab = "overview";   // Oversikt er forsiden

/* ---------------- nettverk ---------------- */

async function api(path, body) {
  const headers = body === undefined ? {} : { "Content-Type": "application/json" };
  /* Menneskenoekkelen sendes som et EGET hode, ikke som en informasjonskapsel.
   * Grunnen staar i ui/LIMITS.md: et egendefinert hode kan en fremmed
   * nettside ikke sette uten en CORS-forhaandssjekk appen ikke svarer paa,
   * saa modellen er immun mot CSRF av seg selv - mens en informasjonskapsel
   * ville blitt sendt automatisk fra hvilken som helst side. */
  const nokkel = menneskeNokkel();
  if (nokkel) headers[HUMAN_KEY_HEADER] = nokkel;

  const res = await fetch(path, {
    method: body === undefined ? "GET" : "POST",
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!res.ok) {
    let detalj = "";
    try {
      const feil = await res.json();
      detalj = typeof feil.detail === "string" ? feil.detail : "";
    } catch (e) {
      /* Ikke JSON. Da har vi bare statuskoden, og den er nok. */
    }
    const exc = new Error(detalj || path + " svarte " + res.status);
    exc.status = res.status;
    throw exc;
  }
  return res.json();
}

/* ---------------- menneskenoekkelen («BankID»-steget) ----------------
 *
 * Valget: noekkelen skrives inn i et felt og lagres i `sessionStorage`, og
 * sendes som `X-Lonewatch-Human-Key` paa hvert kall. Den ligger ALDRI i en
 * statisk fil nettleseren laster ned.
 *
 * Hvorfor sessionStorage og et hode, og ikke en httpOnly-informasjonskapsel:
 *   - et egendefinert hode kan ikke settes fra en fremmed nettside uten en
 *     CORS-forhaandssjekk, saa godkjenningen er ikke naabar via CSRF. En
 *     informasjonskapsel sendes automatisk, og da maatte vi i tillegg bygget
 *     et CSRF-token.
 *   - `sessionStorage` er tomt naar fanen lukkes. Ingen blir staaende
 *     innlogget paa en projektor.
 * Hva det IKKE loeser staar i ui/LIMITS.md: noekkelen er lesbar for JS som
 * kjoerer paa siden, og den ligger i klartekst i et miljoe og en fil paa
 * maskinen. En agent med Bash kan lese den.
 */
const HUMAN_KEY_HEADER = "X-Lonewatch-Human-Key";
const HUMAN_NOKKEL_LAGER = "lonewatch:menneskenokkel";

let menneskeOk = false;        // har noekkelen vi har blitt godtatt?
let menneskePseudonym = null;  // hva loggen vil si at det var

function menneskeNokkel() {
  try {
    return sessionStorage.getItem(HUMAN_NOKKEL_LAGER) || "";
  } catch (e) {
    /* Privat vindu eller blokkert lagring. Da maa noekkelen skrives inn paa
     * nytt hver gang, og det er riktigere enn aa legge den et annet sted. */
    return "";
  }
}

function settMenneskeNokkel(verdi) {
  try {
    if (verdi) sessionStorage.setItem(HUMAN_NOKKEL_LAGER, verdi);
    else sessionStorage.removeItem(HUMAN_NOKKEL_LAGER);
  } catch (e) {
    /* ingen lagring: noekkelen gjelder bare dette kallet */
  }
}

function kanGodkjenne() {
  return menneskeOk;
}

async function sjekkMenneskeNokkel() {
  /* To spoersmaal, i denne rekkefoelgen: er laasen satt opp i det hele tatt,
   * og holder noekkelen vi alt har? */
  try {
    const svar = await api("/api/human");
    if (svar.configured === false) {
      menneskeOk = false;
      menneskePseudonym = null;
      tegnLaas("av");
      return;
    }
  } catch (e) {
    tegnLaas("feil", e.message);
    return;
  }

  if (!menneskeNokkel()) {
    menneskeOk = false;
    menneskePseudonym = null;
    tegnLaas("laast");
    return;
  }
  try {
    const svar = await api("/api/human/check", {});
    menneskeOk = svar.ok === true;
    menneskePseudonym = svar.pseudonym || null;
    tegnLaas(menneskeOk ? "aapen" : "laast");
  } catch (e) {
    menneskeOk = false;
    menneskePseudonym = null;
    settMenneskeNokkel("");
    tegnLaas(e.status === 503 ? "av" : "laast", e.message);
  }
}

function tegnLaas(tilstand, melding) {
  const boks = el("human-lock");
  if (!boks) return;
  const tittel = el("human-lock-title");
  const notis = el("human-lock-note");
  const hint = el("human-hint");
  const felt = el("human-key");
  const innlogging = el("human-login");
  const utKnapp = el("human-logout");

  boks.classList.remove("hidden", "is-open", "is-off");
  innlogging.classList.remove("hidden");
  utKnapp.classList.add("hidden");
  hint.className = "app-hint";
  hint.textContent = melding || "";

  if (tilstand === "aapen") {
    boks.classList.add("is-open");
    tittel.textContent = "Godkjenning er låst opp";
    notis.textContent =
      "Loggen vil føre godkjenningene dine på " +
      (menneskePseudonym || "et pseudonym") +
      ". Nøkkelen glemmes når du lukker fanen.";
    felt.value = "";
    innlogging.classList.add("hidden");
    utKnapp.classList.remove("hidden");
    return;
  }
  if (tilstand === "av") {
    boks.classList.add("is-off");
    tittel.textContent = "Godkjenning er slått av";
    notis.textContent =
      "LONEWATCH_HUMAN_KEY er ikke satt i terminalen som kjører appen, eller " +
      "den er satt til samme verdi som agentnøkkelen. Ingenting kan " +
      "godkjennes. Kjør «python -m agent_gateway.oppsett», gjør «source " +
      ".lonewatch-agent-env», og start appen på nytt.";
    innlogging.classList.add("hidden");
    return;
  }
  if (tilstand === "feil") {
    tittel.textContent = "Fikk ikke sjekket låsen";
    notis.textContent = "Appen svarte ikke på /api/human. Prøv å laste siden på nytt.";
    return;
  }
  tittel.textContent = "Godkjenning er låst";
  notis.textContent =
    "Et rødt kort kan bare godkjennes av et menneske med menneskenøkkelen. " +
    "Den står i .lonewatch-agent-env (LONEWATCH_HUMAN_KEY). Agentnøkkelen duger ikke.";
}

/* ---------------- porten foran alt som styrer demoen ----------------
 *
 * «Spill av hendelsen», «Nullstill», «Prøv selv», stroemmen og «Bryt loggen»
 * krever naa den samme menneskenoekkelen som godkjenningen: de SKRIVER i
 * loggen, og en `allow` fra dem gaar til utfoereren. Se `_demo_guard` i
 * ui/app.py.
 *
 * Valget her: knappene blir ikke borte, og de blir ikke graa uten forklaring.
 * De sier hva som mangler, og de sender deg dit noekkelen skrives inn. En
 * knapp som ikke gjoer noe er verre enn en knapp som sier hvorfor. */

function krevOpplast(handling) {
  if (menneskeOk) return true;
  const b = el("verify-banner");
  b.classList.remove("hidden");
  b.classList.add("is-bad");
  b.textContent =
    handling + " krever menneskenøkkelen. Lås opp øverst i Godkjenning " +
    "først — demoen skriver i den låste loggen, og det skal et menneske stå " +
    "bak.";
  showTab("queue");
  const felt = el("human-key");
  if (felt && !felt.classList.contains("hidden")) felt.focus();
  return false;
}

/* Er siden laast, viser vi det én gang, i stedet for at hver knapp sier det
 * hver gang. `locked` kommer fra /api/state (se ui/app.py).
 *
 * IKKE paa «Prøv selv». Der staar beskjeden i skjemaet, rett under knappen man
 * nettopp trykket (`#c-error`), og det er riktigere sted: den som har fylt ut
 * et skjema skal lese svaret ved skjemaet. Banneret i tillegg ville bare tatt
 * tre linjer av en fane som alt er den hoeyeste i appen - se ui/LIMITS.md om
 * loddrett plass. */
const LAAST_BANNER_FANER = new Set(["overview", "before", "queue", "after"]);

function renderLaastSide() {
  const notis = el("locked-banner");
  if (!notis) return;
  const laast =
    Boolean(latest && latest.locked) && LAAST_BANNER_FANER.has(activeTab);
  notis.classList.toggle("hidden", !laast);
  if (laast) {
    /* Kort med vilje: banneret staar over ALLE fem fanene, og hver linje det
     * tar er en linje mindre til innholdet. Hele begrunnelsen staar under
     * «Begrensninger» og i ui/LIMITS.md. */
    notis.textContent =
      "Låst side: tellere og status, maskert mottaker, ingen fritekst og " +
      "ingen regelnavn. Lås opp i Godkjenning for hele saken.";
  }
}

/* ---------------- den rolige strømmen ---------------- */

function startFeed() {
  stopFeed();
  /* Uten noekkelen svarer /api/feed/step 403. En timer som spoer hvert andre
   * sekund og blir nektet hver gang, er stoey - ikke en demo. */
  if (!menneskeOk) return;
  feedTimer = setInterval(async () => {
    if (latest && latest.feed && latest.feed.done) {
      stopFeed();
      /* Alt er gjennom. Sjekk loggen én gang til, slik at ringen viser
       * tilstanden for HELE kjoeringen og ikke bare starten. */
      await verifyQuietly();
      return;
    }
    try {
      const out = await api("/api/feed/step", {});
      apply(out.state);
    } catch (e) {
      stopFeed();
    }
  }, FEED_MS);
}

function stopFeed() {
  if (feedTimer) clearInterval(feedTimer);
  feedTimer = null;
}

/* ---------------- hendelsen ---------------- */

async function storyPlay() {
  if (!krevOpplast("Å spille av hendelsen")) return;
  stopStory();
  const out = await api("/api/story/start", {});
  apply(out.state);
  el("story-band").classList.remove("hidden");
  el("story-band").classList.add("live");
  scheduleStory(0);
}

function scheduleStory(delayMs) {
  storyTimer = setTimeout(async () => {
    const out = await api("/api/story/step", {});
    apply(out.state);
    const s = out.story;
    if (s.done) {
      el("story-band").classList.remove("live");
      await storyFerdig();
      return;
    }
    const gap = Math.max(0, (s.next_at_second - s.current_second)) * 1000 / STORY_SPEED;
    scheduleStory(gap);
  }, delayMs);
}

function stopStory() {
  if (storyTimer) clearTimeout(storyTimer);
  storyTimer = null;
}

async function storyNext() {
  if (!krevOpplast("Å gå videre i hendelsen")) return;
  stopStory();
  const out = await api("/api/story/step", {});
  apply(out.state);
  if (out.story.done) {
    el("story-band").classList.remove("live");
    await storyFerdig();
  }
}

/* Hendelsen la elleve steg i loggen. Sjekken fra foer gjaldt loggen uten dem,
 * saa den kjoeres paa nytt med en gang - ikke foerst naar noen trykker. */
async function storyFerdig() {
  await verifyQuietly();
  if (activeTab === "after") await loadAfter();
  else renderChainStrip();
}

/* ---------------- tegning ---------------- */

function apply(state) {
  latest = state;
  render();
  /* Dashbordet skal foelge med mens stroemmen gaar og etter Nullstill. Vi
   * henter bare naar fanen faktisk er synlig - ingen grunn til aa regne ut
   * tall ingen ser. */
  if (activeTab === "overview") refreshOverview();
  if (activeTab === "after") oppdaterEtter();
}

/* Etter staar aapen mens stroemmen gaar, og loggen vokser under foettene paa
 * den. Da maa striper og tabell foelge med SAMMEN: en striper som sier «Siste
 * blokk #48» over en tabell som stopper paa #41 er den samme feilen igjen, to
 * tall fra to oejeblikk. `verify_stale` kommer fra ui/state.py og sier naar
 * sjekken ikke lenger gjelder loggen slik den er. */
let etterOppdateres = false;

async function oppdaterEtter() {
  if (activeTab !== "after" || etterOppdateres) return;
  if (!latest || !latest.log || !latest.log.verify_stale) return;
  etterOppdateres = true;
  try {
    await verifyQuietly();
    await hentLogg();
  } finally {
    etterOppdateres = false;
  }
  renderChainStrip();
}

function render() {
  if (!latest) return;
  renderStory(latest.story);
  renderQueue();
  renderCalm(latest.calm, latest.calm_total);
  renderBefore(latest.before);
  renderCustom(latest.custom || []);
  renderLaastSide();

  syncNavCounts();

  const err = latest.log && latest.log.error;
  const box = el("log-error");
  box.classList.toggle("hidden", !err);
  if (err) box.textContent = err;

  // Nullstilling begynner en ny loggfil. Vi sier hvor den gamle ble lagt,
  // slik at ingen logg forsvinner i det skjulte.
  const archived = latest.log && latest.log.archived;
  const note = el("log-note");
  note.classList.toggle("hidden", !archived);
  if (archived) {
    note.textContent = "Ny logg startet. Forrige logg ligger uendret i " + archived;
    /* Linjen er klippet paa skjermen for aa spare hoeyde. Hele stien skal
       fortsatt vaere tilgjengelig uten aa gaa i loggfilen. */
    note.title = archived;
  }

  el("btn-story").disabled = latest.story.running;
}

function renderStory(s) {
  if (!s || s.index === 0) {
    el("story-band").classList.add("hidden");
    return;
  }
  el("story-band").classList.remove("hidden");
  const last = s.log.length ? s.log[s.log.length - 1] : null;
  el("story-clock").textContent = (last ? last.at_second : 0) + " s";
  el("story-title").textContent = last ? last.title : s.title;
  el("story-detail").textContent = last ? last.detail : s.subtitle;
  el("story-step-count").textContent = "steg " + s.index + " av " + s.total_steps;
  el("story-fill").style.width =
    Math.min(100, ((last ? last.at_second : 0) / s.duration_seconds) * 100) + "%";
  el("btn-story-next").disabled = s.done;
}

function buildNav() {
  el("app-nav").innerHTML = VIEWS.map((v) =>
    '<button type="button" class="lw-nav-item" data-tab="' + v.tab + '" ' +
    'title="' + esc(v.navn) + '" aria-label="' + esc(v.navn) + '">' +
    '<span class="app-nav-icon" data-icon="' + v.ikon + '"></span>' +
    '<span class="app-nav-text">' + esc(v.navn) + '</span>' +
    '<span class="app-nav-count hidden" data-count="' + v.tab + '"></span>' +
    "</button>"
  ).join("");
  /* Ikonene tegnes med designsystemets egen Icon-komponent, saa strek,
     tykkelse og stoerrelse er de samme som i dashbordet. */
  if (globalThis.Lonewatch && globalThis.Lonewatch.Icon && typeof ReactDOM !== "undefined") {
    document.querySelectorAll("#app-nav [data-icon], .app-bell [data-icon]").forEach((slot) => {
      ReactDOM.createRoot(slot).render(
        React.createElement(globalThis.Lonewatch.Icon, {
          name: slot.getAttribute("data-icon"), size: 18,
        })
      );
    });
  }
}

/* Bjella i topplinjen. Samme tall som menyvalget, men synlig uansett hvilken
 * visning man staar i. */
function syncBell() {
  if (!latest) return;
  const n = latest.waiting.length;
  const boks = el("bell-count");
  boks.classList.toggle("hidden", n === 0);
  boks.textContent = n;
  const knapp = el("btn-bell");
  knapp.classList.toggle("is-alert", n > 0);
  knapp.setAttribute(
    "aria-label",
    n === 0 ? "Ingenting venter paa et menneske"
            : n + (n === 1 ? " varsel venter paa et menneske" : " varsler venter paa et menneske")
  );
}

/* Teller paa menyvalget, saa man ser at noe venter uten aa gaa inn. */
function syncNavCounts() {
  if (!latest) return;
  const tall = {
    queue: latest.waiting.length,
    before: (latest.before && latest.before.scanned.length) || 0,
    custom: (latest.custom && latest.custom.length) || 0,
  };
  document.querySelectorAll("#app-nav [data-count]").forEach((e) => {
    const n = tall[e.getAttribute("data-count")];
    e.classList.toggle("hidden", !n);
    e.classList.toggle("is-red", e.getAttribute("data-count") === "queue" && n > 0);
    if (n) e.textContent = n;
  });
  el("app-dot").classList.toggle("is-alert", latest.waiting.length > 0);
  syncBell();
}

function chips(decision) {
  const parts = (decision.reasons || []).map(
    (r) => '<span class="app-chip is-red">' + esc(RULE_TEXT[r] || r) + "</span>"
  );
  parts.push('<span class="app-chip">risiko: ' + esc(RISK_TEXT[decision.risk] || decision.risk) + "</span>");
  return '<div class="app-chips">' + parts.join("") + "</div>";
}

function who(card) {
  const r = card.request;
  const bits = [
    '<span class="app-agent">' + esc(card.agent_label) + "</span>",
    esc(card.action_label),
  ];
  if (r.recipient) bits.push("til " + esc(r.recipient));
  if (card.source === "story") bits.push("hendelsen");
  if (card.source === "custom") bits.push('<span class="app-mine">skrevet av deg</span>');
  if (card.source === "agent") bits.push('<span class="app-live">ekte agent</span>');
  return '<div class="app-who">' + bits.join(' <span class="app-sep">&middot;</span> ') + "</div>";
}

/* ---------------- Godkjenning: koe til venstre, detalj til hoeyre ----------------
 *
 * Kjernen staar uroert: et menneske maa skrive BELOEPET foer Godkjenn blir
 * trykkbar. Det er hele poenget med et roedt varsel, og det kan ikke klikkes
 * bort. Resten av panelet er bare det som ligger i loggen fra foer, satt opp
 * slik at man kan lese seg til en avgjoerelse uten aa aapne et terminalvindu.
 */

let valgt = null;          // request_id paa det som staar aapent til hoeyre
let trailCache = {};       // request_id -> hva agenten gjorde foer
let logData = null;        // /api/log: logglinjer + feller
let logFilter = "alle";

function alleKort() {
  if (!latest) return [];
  /* Roedt foerst: det er det eneste som venter paa et menneske. Deretter det
   * vi stoppet selv, og til slutt det som alt er besvart. */
  return [].concat(latest.waiting || [], latest.blocked || [], latest.answered || []);
}

function koeStatus(card) {
  if (card.status === "waiting") return { klasse: "is-red", merke: "venter paa deg", tekst: "Venter" };
  if (card.decision.verdict === "block") return { klasse: "is-stopped", merke: "stoppet", tekst: "Stoppet" };
  if (card.status === "approved") return { klasse: "is-yes", merke: "godkjent", tekst: "Godkjent" };
  if (card.status === "rejected") return { klasse: "is-no", merke: "avvist", tekst: "Avvist" };
  return { klasse: "", merke: "", tekst: "" };
}

/* En tom liste er ikke en feil, men den er heller ikke et svar.
 *
 * «Ingenting ennå.» forteller deg at du ser riktig, men ikke hvorfor det er
 * tomt eller hva du kan gjoere med det. Hver tomtilstand her sier begge deler,
 * og tilbyr veien videre naar det finnes en.
 */
function tomtFelt(tittel, tekst, knapp, maal) {
  return (
    '<div class="app-empty-state">' +
    '<p class="app-empty-title">' + esc(tittel) + "</p>" +
    '<p class="app-empty-text">' + esc(tekst) + "</p>" +
    (knapp
      ? '<button type="button" class="lw-btn lw-btn-quiet app-mini" ' +
        (maal === "story" ? 'data-empty-story="1"' : 'data-tab="' + esc(maal) + '"') +
        ">" + esc(knapp) + "</button>"
      : "") +
    "</div>"
  );
}

function renderQueue() {
  const liste = alleKort();
  const venter = (latest.waiting || []).length;

  const badge = el("waiting-count");
  badge.textContent = venter;
  badge.classList.toggle("is-quiet", venter === 0);

  /* Valget skal ikke hoppe naar stroemmen tegner om. Det foerste roede er
   * standardvalget, fordi det er det som faktisk venter. */
  if (!liste.some((c) => c.request.id === valgt)) {
    valgt = liste.length ? liste[0].request.id : null;
  }

  el("queue-list").innerHTML = liste.length
    ? liste.map((card) => {
        const st = koeStatus(card);
        const r = card.request;
        return (
          '<button type="button" class="app-item ' + st.klasse +
          (r.id === valgt ? " is-open" : "") + '" data-pick="' + esc(r.id) + '">' +
          '<span class="app-item-top">' +
          '<span class="app-item-name">' + esc(lwName(r.id)) + "</span>" +
          '<span class="app-item-state">' + esc(st.tekst) + "</span></span>" +
          '<span class="app-item-mid">' + esc(card.agent_label) +
          ' <span class="app-sep">&middot;</span> ' + esc(card.action_label) + "</span>" +
          '<span class="app-item-sub">' +
          (r.amount != null ? esc(kroner(r.amount)) : esc(r.recipient || r.package_name || "")) +
          "</span></button>"
        );
      }).join("")
    : tomtFelt("Ingenting i køen ennå",
        "Agentene jobber, og alt de har bedt om så langt gikk rett gjennom. " +
        "Kommer det noe et menneske må svare på, dukker det opp her.",
        "Spill av hendelsen", "story");

  renderQueueDetail();
}

/* «Regler som slo inn». Navnene er VAARE egne regelnavn fra gateway, med den
 * norske forklaringen ved siden av - ikke oppdiktede R-numre. */
function reglerBlokk(d) {
  if (!d.reasons || !d.reasons.length) {
    return '<p class="app-empty">Ingen regel slo inn. Forespørselen gikk gjennom som den var.</p>';
  }
  return (
    '<ul class="app-rules">' +
    d.reasons.map((r) =>
      '<li><code class="app-rule-id">' + esc(r) + "</code>" +
      '<span class="app-rule-text">' + esc(RULE_TEXT[r] || "Ingen forklaring lagt inn for denne regelen.") +
      "</span></li>"
    ).join("") +
    "</ul>"
  );
}

/* «Forespurt handling» - den ekte ActionRequest, ordnet slik at feltene
 * reglene faktisk leste staar foerst. Ingenting er lagt til. */
function handlingBlokk(r) {
  const rekkefolge = [
    "id", "agent_id", "action_type", "amount", "recipient", "recipient_known",
    "contains_personal_data", "reversible", "package_name", "source_doc_id",
    "summary", "ts",
  ];
  const ut = {};
  rekkefolge.forEach((k) => { if (r[k] !== undefined) ut[k] = r[k]; });
  Object.keys(r).forEach((k) => { if (ut[k] === undefined) ut[k] = r[k]; });
  return '<pre class="app-json">' + esc(JSON.stringify(ut, null, 2)) + "</pre>";
}

/* «Dette ledet hit» - hva den samme agenten gjorde rett foer, fra loggen. */
function sporBlokk(id) {
  const spor = trailCache[id];
  if (!spor) return '<p class="app-empty">Henter …</p>';
  if (!spor.length) return '<p class="app-empty">Ingenting i loggen før denne.</p>';
  return (
    '<ol class="app-trail">' +
    spor.map((t) =>
      '<li' + (t.er_denne ? ' class="is-here"' : "") + ">" +
      '<span class="app-trail-time">' + esc(klokke(t.ts)) + "</span>" +
      '<span class="app-trail-what">' + esc(t.kall) +
      (t.maal ? ' <span class="app-sep">&middot;</span> ' + esc(t.maal) : "") + "</span>" +
      '<span class="app-trail-out">' + esc(UTFALL_TEXT[t.utfall] || t.utfall) + "</span>" +
      (t.felle ? '<span class="app-chip is-red">felle: ' + esc(t.felle) + "</span>" : "") +
      "</li>"
    ).join("") +
    "</ol>"
  );
}

/* «Feller i dokumenter» - de ekte fellene fra agents/traps, og naar de sist
 * gikk av i denne oekten. Ingen oppdiktede kundetall. */
function fellerBlokk() {
  const feller = (logData && logData.traps) || [];
  if (!feller.length) return "";
  return (
    '<section class="app-block">' +
    '<h3 class="app-block-h">Feller i dokumenter</h3>' +
    '<p class="app-block-sub">Plantet i demoens dokumenter. Her ser du om de har gått av.</p>' +
    '<div class="app-table-wrap"><table class="lw-table app-table"><thead><tr>' +
    "<th>Dokument</th><th>Type</th><th>Hva den ber om</th><th>Sist av</th>" +
    "</tr></thead><tbody>" +
    feller.map((f) =>
      "<tr" + (f.sist ? ' class="is-fired"' : "") + ">" +
      "<td>" + esc(f.doc_id) + "</td>" +
      "<td>" + esc(f.type) + "</td>" +
      "<td>" + esc(f.intent) + "</td>" +
      "<td>" + (f.sist
        ? esc(klokke(f.sist.ts)) + " <span class=\"app-muted\">" + esc(f.sist.agent) + "</span>"
        : '<span class="app-muted">ikke gått av</span>') + "</td></tr>"
    ).join("") +
    "</tbody></table></div></section>"
  );
}

/* ---------------- utfoereren ----------------
 *
 * `card.execution` er svaret fra executor/: ble handlingen gjort, eller ble
 * den ikke gjort. Det finnes ingen tredje mulighet, og teksten kommer fra
 * utfoereren - vi skriver den ikke om her.
 */
const EXEC_TEKST = {
  done: "Utført",
  refused: "Ikke utført",
  failed: "Ikke utført",
  already_attempted: "Ikke utført",
};

function utforingBlokk(card) {
  const e = card.execution;
  if (!e) return "";
  const klasse = e.executed ? "is-done" : "is-not-done";
  return (
    '<div class="app-exec ' + klasse + '">' +
    "<b>" + esc(EXEC_TEKST[e.status] || e.status) + "</b> " +
    esc(e.detail) +
    (e.target ? ' <span class="app-muted">' + esc(e.target) + "</span>" : "") +
    "</div>"
  );
}

function renderQueueDetail() {
  const box = el("queue-detail");
  const card = alleKort().find((c) => c.request.id === valgt);
  if (!card) {
    box.innerHTML =
      '<section class="lw-panel app-detail-panel">' +
      tomtFelt("Velg noe i køen",
        "Her står hele saken: hvilke regler som slo inn, hva agenten " +
        "faktisk ba om, og hva den gjorde rett før.") + "</section>";
    return;
  }

  const r = card.request;
  const d = card.decision;
  const st = koeStatus(card);
  if (!shownAt[r.id]) shownAt[r.id] = Date.now();

  /* Alvorlighet finnes som Decision.risk. Ingen poengsum: vi har ikke noen,
   * og en skala vi ikke maaler ville vaert en paastand. */
  const risiko =
    '<span class="app-sev is-' + esc(d.risk) + '">' +
    esc(RISK_TEXT[d.risk] || d.risk) + "</span>";

  let gate = "";
  if (card.status === "waiting" && !kanGodkjenne()) {
    /* Laast. Knappene tegnes ikke i det hele tatt: en knapp som ser trykkbar
     * ut og gir 403 er en loegn om hva som er mulig. */
    gate =
      '<div class="app-gate is-locked"><div class="app-gate-row">' +
      '<span class="app-hint is-bad">Låst. Lås opp Godkjenning øverst med ' +
      "menneskenøkkelen for å kunne svare på dette.</span>" +
      "</div></div>";
  } else if (card.status === "waiting") {
    if (d.requires_typed_amount) {
      const val = typed[r.id] || "";
      const ok = amountMatches(val, r.amount);
      const hint = card.error
        ? '<span class="app-hint is-bad">' + esc(card.error) + "</span>"
        : ok
        ? '<span class="app-hint is-ok">Stemmer.</span>'
        : '<span class="app-hint">Skriv beløpet nøyaktig for å kunne godkjenne.</span>';
      gate =
        '<div class="app-gate"><label for="amt-' + esc(r.id) + '">' +
        "Skriv beløpet for å godkjenne</label>" +
        '<div class="app-gate-row">' +
        '<input id="amt-' + esc(r.id) + '" inputmode="numeric" autocomplete="off" ' +
        'placeholder="0" value="' + esc(val) + '" data-amt="' + esc(r.id) + '">' +
        '<button class="lw-btn lw-btn-danger" data-approve="' + esc(r.id) + '"' +
        (ok ? "" : " disabled") + ">Godkjenn</button>" +
        '<button class="lw-btn lw-btn-danger-quiet" data-reject="' + esc(r.id) + '">Avvis</button>' +
        hint + "</div></div>";
    } else {
      gate =
        '<div class="app-gate"><div class="app-gate-row">' +
        '<button class="lw-btn lw-btn-danger" data-approve="' + esc(r.id) + '">Godkjenn</button>' +
        '<button class="lw-btn lw-btn-danger-quiet" data-reject="' + esc(r.id) + '">Avvis</button>' +
        (card.error ? '<span class="app-hint is-bad">' + esc(card.error) + "</span>" : "") +
        "</div></div>";
    }
  } else if (card.human) {
    const h = card.human;
    gate =
      '<div class="app-gate is-done">' + esc(st.tekst) +
      (h.employee_pseudonym ? " av " + esc(h.employee_pseudonym) : "") +
      (h.seconds_to_decide != null ? " etter " + Math.round(h.seconds_to_decide) + " s" : "") +
      (h.typed_amount != null ? ", skrev " + esc(kroner(h.typed_amount)) : "") +
      "</div>";
  } else if (d.verdict === "block") {
    gate = '<div class="app-gate is-done">Stoppet av Lonewatch. Ingen kan klikke dette gjennom.</div>';
  }

  /* Hva utfoereren gjorde. `null` betyr at den aldri ble spurt - en roed sak
   * som venter, en avvist sak og en blokkert sak kommer ikke dit. Da staar det
   * ingenting, for det er sant: ingenting skjedde. */
  gate += utforingBlokk(card);

  box.innerHTML =
    '<section class="lw-panel app-detail-panel ' + st.klasse + '">' +
    '<div class="app-detail-head">' +
    "<div>" +
    '<div class="app-detail-id">' + esc(lwName(r.id)) + risiko +
    '<span class="app-raw">' + esc(r.id) + "</span></div>" +
    '<h2 class="app-detail-title">' + esc(d.consequence_text) + "</h2>" +
    who(card) +
    "</div>" +
    '<span class="app-item-state ' + st.klasse + '">' + esc(st.tekst) + "</span>" +
    "</div>" +

    gate +

    '<section class="app-block">' +
    '<h3 class="app-block-h">Regler som slo inn</h3>' +
    reglerBlokk(d) +
    "</section>" +

    '<div class="app-block-two">' +
    '<section class="app-block">' +
    '<h3 class="app-block-h">Forespurt handling</h3>' +
    '<p class="app-block-sub">Feltene mellomstasjonen leste. ' +
    "<code>summary</code> er agentens egen forklaring og brukes aldri i vurderingen.</p>" +
    handlingBlokk(r) +
    "</section>" +
    '<section class="app-block">' +
    '<h3 class="app-block-h">Dette ledet hit</h3>' +
    '<p class="app-block-sub">Hva samme agent gjorde rett før, fra loggen.</p>' +
    sporBlokk(r.id) +
    "</section>" +
    "</div>" +

    fellerBlokk() +
    "</section>";

  if (!trailCache[r.id]) hentSpor(r.id);
}

/* Fellene og logglinjene hentes én gang per visning som trenger dem. */
async function hentLogg() {
  try {
    logData = await api("/api/log");
  } catch (e) {
    logData = null;
  }
  if (activeTab === "queue") renderQueueDetail();
  if (activeTab === "after") renderLogTable();
}

async function hentSpor(id) {
  try {
    const svar = await api("/api/trail/" + encodeURIComponent(id));
    trailCache[id] = svar.trail || [];
  } catch (e) {
    trailCache[id] = [];
  }
  if (valgt === id && activeTab === "queue") renderQueueDetail();
}

function renderCalm(list, total) {
  const badge = el("calm-count");
  badge.textContent = total;
  if (!list.length) {
    el("calm").innerHTML = tomtFelt("Ingenting har gått gjennom ennå",
      "Her havner forespørslene Lonewatch slipper videre uten å spørre noen.");
    return;
  }
  el("calm").innerHTML = list
    .map(
      (card) =>
        '<div class="app-quiet-row"><span class="app-tick">&#9679;</span>' +
        '<span class="app-agent">' + esc(card.agent_label) + "</span>" +
        '<span class="app-what">' + esc(card.request.summary) + "</span></div>"
    )
    .join("");
}

/* ---------------- Foer: sandkassen ----------------
 *
 * Skissen hadde versjon, utgiver, SHA, signatur og «tilganger bedt om mot
 * tilganger brukt». `SandboxReport` har ingen av dem, saa de staar ikke her.
 * Vi viser det boksen faktisk rapporterte: navn, verdikt, notat og hvilke
 * adresser tillegget forsoekte aa kontakte.
 */

let valgtPakke = null;

const BEFORE_STATE = {
  blocked: { tekst: "Blokkert", klasse: "is-stopped", merke: "blokkert" },
  clean: { tekst: "Rent", klasse: "is-clean", merke: "rent" },
  not_tested: { tekst: "Ikke testet", klasse: "is-untested", merke: "ikke testet" },
};

function beforeItems(b) {
  if (!b) return [];
  const ut = (b.scanned || []).map((r) => ({
    navn: r.package_name, verdict: r.verdict, notes: r.notes,
    destinations: r.destinations || [], testet: true,
  }));
  (b.untested || []).forEach((u) => ut.push({
    navn: u.package_name, verdict: "not_tested", notes: u.note,
    destinations: [], testet: false,
  }));
  return ut;
}

function renderBefore(b) {
  if (!b) return;
  const items = beforeItems(b);
  el("before-count").textContent = items.length;

  if (!items.some((i) => i.navn === valgtPakke)) {
    valgtPakke = items.length ? items[0].navn : null;
  }

  el("before-list").innerHTML = items.length
    ? items.map((i) => {
        const st = BEFORE_STATE[i.verdict] || { tekst: i.verdict, klasse: "" };
        return (
          '<button type="button" class="app-item ' + st.klasse +
          (i.navn === valgtPakke ? " is-open" : "") +
          '" data-pack="' + esc(i.navn) + '">' +
          '<span class="app-item-top">' +
          '<span class="app-item-name">' + esc(i.navn) + "</span>" +
          '<span class="app-item-state">' + esc(st.tekst) + "</span></span>" +
          '<span class="app-item-sub">' +
          (i.destinations.length
            ? i.destinations.length + " adresse" + (i.destinations.length > 1 ? "r" : "") + " forsøkt"
            : i.testet ? "ingen nettverksforsøk" : "kom aldri i gang") +
          "</span></button>"
        );
      }).join("")
    : tomtFelt("Ingen tillegg er prøvd installert",
        "Sandkassen kjører først når en agent ber om å installere noe. " +
        "Du kan utløse det selv under «Prøv selv» med handlingen " +
        "«Installerer tillegg».",
        "Prøv selv", "custom");

  renderBeforeDetail(b, items);
}

function renderBeforeDetail(b, items) {
  const box = el("before-detail");
  const i = items.find((x) => x.navn === valgtPakke);

  /* En sandkasse som ikke svarte er sin egen beskjed. Den skal ikke skjules
   * bak et valg i listen. */
  const feil = b.error
    ? '<div class="app-banner is-bad">Sandkassen svarte ikke: ' + esc(b.error) + "</div>"
    : "";

  if (!i) {
    box.innerHTML =
      '<section class="lw-panel app-detail-panel">' + feil +
      tomtFelt("Velg et tillegg",
        "Listen til venstre viser hvert tillegg sandkassen har kjørt. " +
        "Trykk på ett for å se hva boksen skrev ned.") + "</section>";
    return;
  }

  const st = BEFORE_STATE[i.verdict] || { tekst: i.verdict, klasse: "" };

  /* «Rent» er det eneste ordet her som kan misforstaas, saa det forklares
   * paa stedet hver gang - ikke i en fotnote nederst. */
  const betyr = {
    clean: "«Rent» betyr at vi ikke så noe. Det er ikke det samme som at tillegget er trygt.",
    blocked: "Boksen stoppet tillegget. Ingenting forlot maskinen.",
    not_tested: "Vi fikk aldri sett etter. Vi vet ikke hva tillegget ville gjort.",
  }[i.verdict] || "";

  const adresser = i.destinations.length
    ? '<table class="lw-table app-table"><thead><tr><th>Vert</th><th>Resultat</th></tr></thead><tbody>' +
      i.destinations.map((d) =>
        "<tr><td>" + esc(d) + '</td><td><span class="app-tag is-blocked">Blokkert</span></td></tr>'
      ).join("") +
      "</tbody></table>" +
      '<p class="app-block-sub">Sandkassen svarer nei på alt nettverk. ' +
      "Adressene er det tillegget <em>prøvde</em> på, ikke noe som gikk ut.</p>"
    : '<p class="app-empty">' +
      (i.testet ? "Tillegget forsøkte ikke nettverk mens det kjørte."
                : "Ingen adresser: tillegget kom aldri i gang.") +
      "</p>";

  box.innerHTML =
    '<section class="lw-panel app-detail-panel ' + st.klasse + '">' + feil +
    '<div class="app-detail-head"><div>' +
    '<div class="app-detail-id">' + esc(i.navn) + "</div>" +
    '<h2 class="app-detail-title">' + esc(betyr) + "</h2>" +
    "</div>" +
    '<span class="app-item-state ' + st.klasse + '">' + esc(st.tekst) + "</span></div>" +

    '<section class="app-block">' +
    '<h3 class="app-block-h">Hva boksen skrev ned</h3>' +
    '<p class="app-note-body">' + esc(i.notes || "Ingen notat.") + "</p>" +
    "</section>" +

    '<section class="app-block">' +
    '<h3 class="app-block-h">Nettverksforsøk</h3>' +
    adresser +
    "</section>" +

    '<div class="app-detail-foot">' +
    '<button class="app-limits" type="button" data-limits="sandkassen">' +
    "Hva sandkassen ikke klarer</button></div>" +
    "</section>";
}

/* ---------------- Oversikt: dashbordet ---------------- */

/* Dashbordet tegnes ALDRI uten et `data`-objekt vi har laget selv. Uten det
 * ville React falt tilbake paa LONEWATCH_DATA i bundle.js, som er eksempeldata
 * med isExample: true - og eksempeltall skal aldri vises som om de var ekte. */
let dashboardRoot = null;
let dashboardData = null;

function dashboardReady() {
  return (
    typeof React !== "undefined" &&
    typeof ReactDOM !== "undefined" &&
    globalThis.Lonewatch &&
    globalThis.Lonewatch.Panel &&
    globalThis.Lonewatch.StatCard
  );
}

/* Samme tallformat som dashbordet bruker internt. Mangler tallet, blir det
 * «–» - aldri 0, for de to betyr ikke det samme. */
function dashNum(n) {
  if (typeof n !== "number" || !isFinite(n)) return "–";
  return new Intl.NumberFormat("nb-NO").format(n);
}

/* «Venter paa deg» erstatter reklamekortet.
 *
 * Reklamekortet solgte en funksjon til noen som alt hadde aapnet appen. Dette
 * feltet er det eneste paa forsiden som kan kreve noe av deg akkurat naa, saa
 * det er det som skal staa der. Alt i det kommer fra `waiting_for_you()`:
 * ingen oppdiktet kunde, intet poengtall. */
function venterKort(w, h, laast) {
  if (w === "ukjent") {
    return h("section", { className: "lw-panel app-waiting is-unknown" },
      h("div", { className: "app-waiting-head" },
        h(globalThis.Lonewatch.Icon, { name: "alert", size: 18 }),
        h("span", null, "Venter på deg")),
      h("p", { className: "app-waiting-title" }, "Vi får ikke svar fra Lonewatch"),
      h("p", { className: "app-waiting-sub" },
        "Vi vet ikke om noe venter på deg akkurat nå. Prøv igjen."));
  }
  if (!w) {
    return h("section", { className: "lw-panel app-waiting is-calm" },
      h("div", { className: "app-waiting-head" },
        h(globalThis.Lonewatch.Icon, { name: "check", size: 18 }),
        h("span", null, "Venter på deg")),
      h("p", { className: "app-waiting-title" }, "Ingenting venter på deg"),
      h("p", { className: "app-waiting-sub" },
        "Ingen røde varsler står ubesvart. Kommer det et, står det her."));
  }

  const linje = [w.agent, w.action].filter(Boolean).join(" · ");
  const detalj = [
    w.amount != null ? kroner(w.amount) : null,
    w.recipient ? "til " + w.recipient : null,
  ].filter(Boolean).join(" · ");

  return h("section", { className: "lw-panel app-waiting" },
    h("div", { className: "app-waiting-head" },
      h(globalThis.Lonewatch.Icon, { name: "alert", size: 18 }),
      h("span", null, "Venter på deg"),
      w.waiting_total > 1
        ? h("span", { className: "app-waiting-more" },
            "1 av " + w.waiting_total + " røde")
        : null),
    h("p", { className: "app-waiting-who" }, linje),
    detalj ? h("p", { className: "app-waiting-amount" }, detalj) : null,
    /* Konsekvensteksten navngir mottakeren i klartekst, og regelnavnene er
       oppskriften paa hva som maa endres for aa slippe gjennom. Begge deler
       tar `minimized_overview()` bort uten menneskenoekkelen - her staar den
       faste setningen i stedet, saa kortet ikke ser ut som om det mangler
       data. Se ui/state.py. */
    laast
      ? h("p", { className: "app-waiting-title" },
          "Rød. Et menneske må svare. Lås opp i Godkjenning for å se " +
          "hele mottakeren, hva som skjer og hvilke regler som slo til.")
      : h("p", { className: "app-waiting-title" }, w.consequence_text),
    /* Hvorfor den er rød, med våre egne regelnavn. Står her fordi kortet
       ellers ber deg om å ta stilling til noe uten å si hva som utløste det. */
    !laast && w.reasons && w.reasons.length
      ? h("ul", { className: "app-waiting-rules" }, w.reasons.map((r, i) =>
          h("li", { key: i },
            h("span", { className: "app-status-dot is-red" }),
            RULE_TEXT[r] || r)))
      : null,
    h("button", {
      type: "button",
      /* Lavendel: knappen navigerer, den godkjenner ingenting. Rødt er
         forbeholdt knappen som faktisk avgjør saken. */
      className: "lw-btn lw-btn-primary app-waiting-cta",
      onClick: function () { valgt = w.request_id; showTab("queue"); },
    }, laast ? "Lås opp og se saken" : "Se og godkjenn"));
}

/* Dashbordet settes sammen av designsystemets egne deler i stedet for aa kalle
 * `Dashboard`. Grunnen er enkel: `Dashboard` tegner sin EGEN `.lw-backdrop`,
 * `.lw-shell` og sidemeny, og appen har alt en. To sidemenyer paa samme side
 * ville vaert to menyer som ikke visste om hverandre. Vi roerer ikke
 * bundle.js - vi bruker bare delene den eksporterer. */
function dashInnhold(h) {
  const L = globalThis.Lonewatch;
  const d = dashboardData || {};
  const t = (d.text && d.text.no) || {};
  const n = d.counts || {};
  const lc = d.logChain || {};
  const sb = d.sandbox || {};
  const lg = d.log || {};
  const titler = t.stats || ["Handlinger vurdert", "Røde varsler", "Blokkert"];

  const status = (st) => (st === "ok" ? "OK" : st === "broken" ? "Feil" : "–");

  /* De tre tellerne. Hvert kort er en knapp som faktisk gaar et sted:
   * et tall uten vei videre er en paastand, ikke en inngang. */
  const kort = [
    {
      tittel: titler[0],
      verdi: n.evaluated,
      rader: [{ label: t.allowed || "Sluppet gjennom", value: dashNum(n.allowed) }],
      hint: "Se alle i loggen",
      gaa: function () { showTab("after"); },
    },
    {
      tittel: titler[1],
      verdi: n.red,
      rader: [
        { label: "Venter på menneske", value: dashNum(n.waitingForHuman) },
        { label: t.followed || "Fulgt opp", value: dashNum(n.followedUp) },
      ],
      hint: "Gå til Godkjenning",
      gaa: function () { showTab("queue"); },
    },
    {
      tittel: titler[2],
      verdi: n.blocked,
      rader: [],
      hint: "Se de stoppede i loggen",
      /* Samme filter som knappen «Stoppet» i Etter-fanen setter. */
      gaa: function () { logFilter = "stoppet"; showTab("after"); },
    },
  ];

  const harTall = typeof n.evaluated === "number" && n.evaluated > 0;

  return [
    h("div", { className: "lw-row-top app-dash-top", key: "top" },
      venterKort(d.waiting, h, d.locked),
      h("div", { className: "lw-col" },
        h(L.Panel, { title: t.activity || "Agentaktivitet" },
          harTall
            ? h("div", { className: "lw-stats" }, kort.map(function (k, i) {
                return statKort(k, i, h);
              }))
            /* Tre nuller sier ikke hva som mangler. Dette gjoer. */
            : h("div", { className: "app-empty-state" },
                h("p", { className: "app-empty-title" }, "Ingen handlinger vurdert ennå"),
                h("p", { className: "app-empty-text" },
                  "Her kommer tre tall så snart agentene begynner: hvor mange " +
                  "handlinger som er vurdert, hvor mange som ble røde og måtte " +
                  "til et menneske, og hvor mange Lonewatch stoppet selv.")))),
      ),

    h("div", { className: "lw-row-bottom app-dash-bottom", key: "bottom" },
      h(L.Panel, {
        title: t.table || "Agenter",
        action: h("button", {
          type: "button", className: "lw-link",
          onClick: function () { showTab("queue"); },
        }, "Se køen", h("span", { className: "lw-link-dot" },
          h(L.Icon, { name: "arrowRight", size: 11, strokeWidth: 2.6 }))),
      }, agentTabell(d.agents || [], t.cols, h)),
      h("div", { className: "lw-col" },
        /* Loggkjeden. Hele panelet er en knapp: den kjoerer den samme sjekken
           «Sjekk loggen» i topplinjen kjoerer, og gaar til Etter-fanen der
           svaret staar i sin helhet. */
        h(L.Panel, { className: "app-dash-click" },
          h("button", {
            type: "button",
            className: "lw-score app-panel-btn",
            onClick: function () { showTab("after"); verify(); },
            title: "Sjekk loggen på nytt og gå til Etter",
          },
            h("div", null,
              h("h2", { className: "lw-panel-title" }, t.logChain || "Loggkjede"),
              h("p", { className: "lw-panel-sub" }, t.logChainSub || "Sjekk av logg"),
              h("p", { className: "lw-score-target" },
                lc.checkedAt
                  ? ["Sist sjekket: ", h("b", { key: "b" }, klokke(lc.checkedAt))]
                  : "Ikke sjekket ennå. Trykk her for å sjekke.")),
            /* 96 i stedet for designsystemets 124. Ringen er den samme
               komponenten med den samme geometrien - den er bare tegnet
               mindre, slik at hele Oversikt faar plass paa 1440x900. */
            h(L.StatusRing, {
              size: 96,
              status: lc.status, display: status(lc.status),
              label: t.logChain || "Loggkjede",
            }))),
        h(L.Panel, { className: "app-dash-click" },
          h("div", { className: "lw-status-rows" },
            statusRad(t.sandboxRow || "Sandkasse",
              typeof sb.tested === "number" && sb.tested > 0
                ? dashNum(sb.tested) + " testet, " + dashNum(sb.blocked) + " blokkert"
                : "Ingen tillegg prøvd ennå",
              function () { showTab("before"); }, h),
            statusRad("Logglinjer",
              /* Tallet foerst, status etter. «OK» alene sier ikke om det er OK
                 for null linjer eller for hundre. */
              dashNum(lg.lines) + " · " + status(lg.status),
              function () { showTab("after"); }, h)))),
    ),
  ];
}

/* Ett tellerkort. Samme deler som designsystemets `StatCard` - `lw-stat`,
 * `lw-stat-title`, `lw-stat-value`, `lw-stat-row` - men uten kurven, og som en
 * knapp i stedet for en `article`.
 *
 * Kurven er borte med vilje. Den hadde en ekte serie bak seg (ett punkt per
 * tidsboette), men ingen akse, ingen skala og ingen enhet: fjorten boetter over
 * en oppdiktet tidslinje ser ut som en maaling uten aa vaere lesbar som en.
 * En dommer skal se tallet paa et sekund, og kurven var det eneste som stod
 * mellom oeyet og tallet. */
function statKort(k, i, h) {
  return h("button", {
    key: i, type: "button", className: "lw-stat app-stat-btn",
    onClick: k.gaa, title: k.hint,
  },
    h("h3", { className: "lw-stat-title" }, k.tittel),
    h("p", { className: "lw-stat-value" }, dashNum(k.verdi)),
    k.rader.map(function (r, j) {
      return h("div", { key: j, className: "lw-stat-row" },
        h("span", null, r.label), h("i"), h("b", null, r.value));
    }),
    h("span", { className: "app-stat-hint" }, k.hint,
      h(globalThis.Lonewatch.Icon, { name: "arrowRight", size: 11, strokeWidth: 2.6 })));
}

/* En rad i statusruten, som knapp. Samme `lw-status-row` som
 * designsystemets `StatusRows`, bare klikkbar. */
function statusRad(navn, verdi, gaa, h) {
  return h("button", {
    key: navn, type: "button", className: "lw-status-row app-panel-btn",
    onClick: gaa,
  },
    h("h2", { className: "lw-panel-title" }, navn),
    h("span", null, verdi));
}

/* Agenttabellen tegnes her i stedet for med `AgentTable`.
 *
 * `AgentTable` skriver fem rene tall. Et tall sier hvor mange, men ikke hvor
 * mye det haster: «2» i kolonnen Røde ser ut som «2» i kolonnen Handlinger.
 * Pillene gir de tre utfallene hver sin farge, og prikken foran navnet sier om
 * agenten har noe som venter paa et menneske akkurat naa.
 *
 * Null vises som en strek, ikke som en pille. En tom pille ville trukket
 * oppmerksomhet mot det som IKKE skjedde. */
function agentTabell(rader, kolonner, h) {
  const kols = kolonner || ["Agent", "Handlinger", "Røde", "Blokkert", "Sluppet gjennom"];

  if (!rader.length) {
    return h("div", { className: "app-empty-state" },
      h("p", { className: "app-empty-title" }, "Ingen agenter har gjort noe ennå"),
      h("p", { className: "app-empty-text" },
        "Den rolige strømmen slipper gjennom én forespørsel hvert par sekund. " +
        "Vil du se alt på én gang, trykk «Spill av hendelsen» i topplinjen."));
  }

  /* Hvilke agenter har noe som venter? Fra kortene, ikke fra en egen teller. */
  const venter = new Set(
    ((latest && latest.waiting) || []).map((c) => c.request.agent_id)
  );

  const pille = (verdi, slag) => {
    if (typeof verdi !== "number") return h("span", { className: "app-muted" }, "–");
    if (verdi === 0) return h("span", { className: "app-muted" }, "–");
    return h("span", { className: "app-pill is-" + slag }, dashNum(verdi));
  };

  return h("table", { className: "lw-table app-agents" },
    h("thead", null, h("tr", null, kols.map((c, i) =>
      h("th", { key: i, scope: "col" }, c)))),
    h("tbody", null, rader.map((ag, i) => {
      const navn = (ag.name && (ag.name.no || ag.name.en)) || ag.id;
      const har = venter.has(ag.id);
      return h("tr", { key: ag.id || i, className: har ? "is-waiting" : "" },
        h("td", null, h("span", { className: "app-agent-cell" },
          h("span", {
            className: "app-status-dot " + (har ? "is-red" : "is-calm"),
            title: har ? "Har noe som venter på et menneske" : "Ingenting venter",
          }),
          navn)),
        h("td", null, dashNum(ag.actions)),
        h("td", null, pille(ag.red, "red")),
        h("td", null, pille(ag.blocked, "blocked")),
        h("td", null, pille(ag.allowed, "allow")));
    })));
}

function drawDashboard() {
  if (!dashboardReady() || !dashboardData) return;
  if (!dashboardRoot) {
    dashboardRoot = ReactDOM.createRoot(el("dashboard-root"));
  }
  const h = React.createElement;
  dashboardRoot.render(h("div", { className: "app-dash" }, dashInnhold(h)));
  /* React har ikke skrevet til DOM ennaa naar render() returnerer. */
  requestAnimationFrame(animerTall);
}

async function refreshOverview() {
  const feil = el("dashboard-error");
  if (!dashboardReady()) {
    feil.classList.remove("hidden");
    feil.textContent =
      "Dashbordet kunne ikke lastes. Filene ligger lokalt i /static/dashboard/ " +
      "og /static/vendor/ - sjekk at de ble med.";
    return;
  }
  try {
    dashboardData = await api("/api/overview");
    feil.classList.add("hidden");
  } catch (e) {
    /* Ingen tall er bedre enn feil tall: alt blir «–». */
    dashboardData = tomtDatasett();
    feil.classList.remove("hidden");
    feil.textContent =
      "Fikk ikke tall fra Lonewatch akkurat nå. Tallene under står som «–» " +
      "til forbindelsen er tilbake.";
  }
  drawDashboard();
}

/* Samme form som /api/overview, men uten tall. Brukes bare hvis backend ikke
 * svarer. Teksten hentes fra bundle.js, som er den eneste delen av
 * eksempeldataene det er trygt aa laane: ren tekst, ingen tall. */
function tomtDatasett() {
  const tekst = globalThis.Lonewatch && globalThis.Lonewatch.data
    ? globalThis.Lonewatch.data.text
    : undefined;
  return {
    isExample: false,
    defaultLang: "no",
    counts: {
      evaluated: null, red: null, blocked: null,
      allowed: null, waitingForHuman: null, followedUp: null,
    },
    agents: [],
    logChain: { status: null, checkedAt: null },
    sandbox: { tested: null, blocked: null },
    log: { status: null, lines: null },
    chartShapes: [],
    /* Ikke `null`: `null` ville betydd «ingenting venter», og det vet vi ikke.
     * «ukjent» gir feltet sin egen tekst i stedet for en beroligende loegn. */
    waiting: "ukjent",
    text: tekst,
  };
}

/* ---------------- Prøv selv ---------------- */

let customHelp = null;

async function loadCustomHelp() {
  if (customHelp) return customHelp;
  customHelp = await api("/api/custom/help");

  el("c-action").innerHTML = customHelp.actions
    .map((a) => '<option value="' + esc(a.value) + '">' + esc(a.label) + "</option>")
    .join("");
  el("c-action").value = "transfer_money";

  el("c-known-note").textContent =
    "Om mottakeren er kjent regnes ut mot demoens liste på " +
    customHelp.known_total +
    " oppdiktede mottakere, for eksempel " +
    customHelp.known_examples.join(", ") +
    ". Alt annet er ukjent.";

  syncCustomFields();
  return customHelp;
}

/* Viser bare feltene handlingen faktisk bruker. */
function syncCustomFields() {
  if (!customHelp) return;
  const valgt = el("c-action").value;
  el("c-amount-wrap").classList.toggle(
    "hidden",
    customHelp.amount_actions.indexOf(valgt) === -1
  );
  el("c-package-wrap").classList.toggle(
    "hidden",
    customHelp.package_actions.indexOf(valgt) === -1
  );
  /* Mottaker gir bare mening for det som sendes ut av huset. */
  const utgaaende = ["transfer_money", "send_email", "share_data"];
  el("c-recipient-wrap").classList.toggle("hidden", utgaaende.indexOf(valgt) === -1);
}

async function sendCustom(ev) {
  ev.preventDefault();
  const feil = el("c-error");
  if (!menneskeOk) {
    /* Her staar meldingen i skjemaet og ikke i banneret: brukeren ser paa
     * feltet de nettopp fylte ut, og skal ikke lure paa om det ble sendt. */
    feil.classList.remove("hidden");
    feil.textContent =
      "Låst. «Prøv selv» sender en ekte forespørsel gjennom Lonewatch og " +
      "skriver i den låste loggen, så den krever menneskenøkkelen. Lås opp " +
      "øverst i Godkjenning.";
    return;
  }
  const knapp = el("c-send");
  knapp.disabled = true;
  try {
    const out = await api("/api/custom", {
      action_type: el("c-action").value,
      summary: el("c-summary").value,
      amount: el("c-amount").value,
      recipient: el("c-recipient").value,
      package_name: el("c-package").value,
      contains_personal_data: el("c-personal").checked,
    });
    feil.classList.toggle("hidden", out.ok);
    if (!out.ok) feil.textContent = out.error;
    apply(out.state);
    if (out.ok) {
      el("c-amount").value = "";
      el("c-recipient").value = "";
      el("c-package").value = "";
      el("c-summary").value = "";
      el("c-personal").checked = false;
    }
  } finally {
    knapp.disabled = false;
  }
}

/* Hva det staar paa et av dine egne kort i "Proev selv".
 *
 * Teksten foelger STATUS, ikke `verdict`. Foer sto det «venter paa et
 * menneske» paa et kort du nettopp hadde besvart selv, fordi `verdict`
 * fortsatt er `red` etter at noen har svart - avgjoerelsen endrer seg ikke
 * naar mennesket svarer, det er statusen som gjoer det. */
const STATUS_TEXT = {
  allow: "gikk gjennom",
  waiting: "venter på et menneske",
  approved: "godkjent av et menneske",
  rejected: "avvist av et menneske",
  blocked: "stoppet",
};

function renderCustom(list) {
  el("custom-count").textContent = list.length;
  if (!list.length) {
    el("custom-list").innerHTML =
      tomtFelt("Du har ikke sendt noe ennå",
        "Fyll ut skjemaet ved siden av. Forespørselen din går gjennom " +
        "nøyaktig samme vei som de 40 i demoen, og havner i den samme loggen.");
    return;
  }
  el("custom-list").innerHTML = list
    .map((card) => {
      const d = card.decision;
      const r = card.request;
      const klasse =
        d.verdict === "block" ? "is-stopped" : d.verdict === "red" ? "is-red" : "is-yes";
      return (
        '<article class="app-flat is-mine ' + klasse + '">' +
        '<div class="app-line1">' +
        '<span class="app-agent">' + esc(card.action_label) + "</span>" +
        '<span class="app-muted">' +
        esc(STATUS_TEXT[card.status] || d.verdict) + "</span>" +
        "</div>" +
        '<div class="app-line2">' + esc(d.consequence_text) + "</div>" +
        '<div class="app-line2 app-said-mini"><b>Du skrev</b> ' + esc(r.summary) + "</div>" +
        chips(d) +
        utforingBlokk(card) +
        "</article>"
      );
    })
    .join("");
}

/* ---------------- Etter ----------------
 *
 * Tre ting, i den rekkefoelgen et menneske trenger dem:
 *   1. Staar loggen? (ekte /api/verify - ingen «400 dagers lagring»)
 *   2. Hva skjedde? (ekte logglinjer, nyeste foerst)
 *   3. Hva maa gjoeres? (ekte oppfoelging, gruppert og prioritert)
 */

function klokke(iso) {
  if (!iso) return "–";
  const d = new Date(iso);
  if (isNaN(d.getTime())) return "–";
  return d.toLocaleTimeString("nb-NO", {
    hour: "2-digit", minute: "2-digit", second: "2-digit", timeZone: "Europe/Oslo",
  });
}

function dagOgKlokke(iso) {
  if (!iso) return "–";
  const d = new Date(iso);
  if (isNaN(d.getTime())) return "–";
  return d.toLocaleString("nb-NO", {
    day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit",
    second: "2-digit", timeZone: "Europe/Oslo",
  });
}

/* Tidskolonnen i Hendelser.
 *
 * Demoen har to klokker, og ui/ kan ikke slaa dem sammen uten aa dikte opp
 * tall: demodataene i agents/ har faste, oppdiktede tidspunkter, mens
 * sandkassen og «Prøv selv» stempler med maskinens ekte klokke. Satt rett
 * under hverandre uten merking ser radene ut til aa komme i feil rekkefoelge.
 *
 * Rekkefoelgen i tabellen er og blir loggens egen (seq, nyeste foerst). Her
 * sier vi bare hvilken klokke tallet kommer fra, slik at et sprang i
 * kolonnen leses som to klokker og ikke som en feil. */
const TIDSBASE = {
  simulert: { merke: "sim", tittel: "Simulert tid fra demodataene i agents/" },
  sanntid: { merke: "nå", tittel: "Ekte klokke på maskinen som kjører demoen" },
};

function tidsCelle(rad) {
  const base = TIDSBASE[rad.tidsbase] || TIDSBASE.simulert;
  return (
    '<td class="app-time" title="' + esc(base.tittel) + ": " +
    esc(dagOgKlokke(rad.ts)) + '">' +
    '<span class="app-time-clock">' + esc(klokke(rad.ts)) + "</span>" +
    '<span class="app-time-base is-' + esc(rad.tidsbase || "simulert") + '">' +
    esc(base.merke) + "</span></td>"
  );
}

/* Striper over Etter: staar loggen?
 *
 * Svaret gjelder loggen slik den var da sjekken ble kjoert. Vokser loggen
 * etterpaa - og det gjoer den hele tiden mens stroemmen gaar - er teksten
 * ikke lenger et svar om DENNE loggen. Det var slik «Loggen er tom.» kunne
 * bli staaende ved siden av «Siste blokk #31»: teksten var fra sjekken rett
 * etter en nullstilling, tallet var fra naa.
 *
 * `verify_stale` kommer fra ui/state.py og sammenligner antall linjer da
 * sjekken ble kjoert med antall linjer naa. Er de ulike, viser vi ingen
 * paastand om kjeden - vi sier at svaret er gammelt. */
function renderChainStrip() {
  const log = (latest && latest.log) || {};
  const v = log.last_verify || null;
  const lines = typeof log.lines === "number" ? log.lines : null;
  const utdatert = Boolean(log.verify_stale);

  if (!v || utdatert) {
    el("chain-strip").className = "lw-panel app-strip";
    el("chain-strip").innerHTML =
      '<div class="app-strip-main"><span class="app-strip-dot"></span>' +
      '<div><div class="app-strip-title">Låst logg</div>' +
      '<div class="app-strip-sub">' +
      (utdatert
        ? "Loggen har fått flere linjer siden sist sjekk. Trykk «Sjekk loggen» " +
          "for et svar som gjelder loggen slik den er nå."
        : "Ikke sjekket ennå. Trykk «Sjekk loggen».") +
      "</div></div></div>" +
      (lines != null
        ? '<dl class="app-strip-facts"><div><dt>Linjer nå</dt><dd>#' +
          esc(String(lines)) + "</dd></div></dl>"
        : "") +
      '<button class="app-limits" type="button" data-limits="loggen">Begrensninger</button>';
    return;
  }

  const ok = Boolean(v.ok);
  /* Antallet kommer fra SJEKKEN, ikke fra oejeblikksbildet. Da kan tallet og
   * teksten ved siden av det aldri komme fra to forskjellige logger. */
  const sjekkede = typeof v.lines === "number" ? v.lines : lines;
  el("chain-strip").className = "lw-panel app-strip " + (ok ? "is-ok" : "is-bad");
  el("chain-strip").innerHTML =
    '<div class="app-strip-main"><span class="app-strip-dot"></span>' +
    "<div>" +
    '<div class="app-strip-title">' +
    (ok ? "Kjeden er hel" : "Kjeden er brutt") + "</div>" +
    '<div class="app-strip-sub">' + esc(v.text || "") + "</div></div></div>" +
    '<dl class="app-strip-facts">' +
    "<div><dt>Siste blokk</dt><dd>#" +
    (sjekkede != null ? esc(String(sjekkede)) : "–") + "</dd></div>" +
    (v.head
      ? '<div><dt>Topphash</dt><dd><code class="app-hash">' + esc(v.head) + "</code></dd></div>"
      : "") +
    (v.seq != null
      ? "<div><dt>Første brudd</dt><dd>#" + esc(String(v.seq)) + "</dd></div>"
      : "") +
    "<div><dt>Sjekket</dt><dd>" + esc(klokke(v.checked_at)) + "</dd></div>" +
    "</dl>" +
    '<button class="app-limits" type="button" data-limits="loggen">Begrensninger</button>';
}

const LOG_FILTRE = [
  { id: "alle", navn: "Alle", felt: "alle" },
  { id: "stoppet", navn: "Stoppet", felt: "stoppet" },
  { id: "menneske", navn: "Til menneske", felt: "menneske" },
];

function renderLogTable() {
  if (!logData || !logData.log) {
    el("log-table").innerHTML = '<p class="app-empty">Henter logglinjer …</p>';
    return;
  }
  const tall = logData.log.counts || {};
  el("log-filter").innerHTML = LOG_FILTRE.map((f) =>
    '<button type="button" class="app-filter-btn' + (logFilter === f.id ? " is-on" : "") +
    '" data-logfilter="' + f.id + '">' + esc(f.navn) +
    '<span class="app-filter-n">' + (tall[f.felt] != null ? tall[f.felt] : "–") + "</span></button>"
  ).join("");

  /* Staar det to klokker i tabellen, maa leseren faa vite det. Staar det bare
   * én, er forklaringen bare stoey. */
  const baser = logData.log.tidsbaser || [];
  el("log-sub").textContent = baser.length > 1
    ? "Hver linje i den låste loggen, nyeste først etter blokknummer. " +
      "«sim» er simulert tid fra demodataene, «nå» er ekte klokke — derfor " +
      "hopper tidskolonnen."
    : "Hver linje i den låste loggen, nyeste først.";

  let rader = logData.log.rows || [];
  if (logFilter === "stoppet") rader = rader.filter((r) => r.utfall === "block" || r.utfall === "blocked");
  if (logFilter === "menneske") rader = rader.filter((r) => r.utfall === "red");

  if (!rader.length) {
    el("log-table").innerHTML = '<p class="app-empty">Ingen linjer med dette filteret.</p>';
    return;
  }

  el("log-table").innerHTML =
    '<div class="app-table-wrap"><table class="lw-table app-table app-log"><thead><tr>' +
    "<th>Tid</th><th>#</th><th>Agent</th><th>Kall</th><th>Mål</th>" +
    "<th>Utfall</th><th>Regel</th><th>Hash</th>" +
    "</tr></thead><tbody>" +
    rader.map((r) =>
      '<tr class="is-' + esc(r.utfall) + '">' +
      tidsCelle(r) +
      '<td class="app-num">' + esc(String(r.seq)) + "</td>" +
      "<td>" + esc(r.agent || "–") + "</td>" +
      "<td>" + esc(r.kall || "–") + "</td>" +
      '<td class="app-target">' + esc(r.maal || "–") + "</td>" +
      '<td><span class="app-tag is-' + esc(r.utfall) + '">' +
      esc(UTFALL_TEXT[r.utfall] || r.utfall) + "</span></td>" +
      "<td>" + (r.regler && r.regler.length
        ? esc(r.regler.join(", "))
        : '<span class="app-muted">–</span>') + "</td>" +
      '<td><code class="app-hash">' + esc(r.hash || "–") + "</code></td>" +
      "</tr>"
    ).join("") +
    "</tbody></table></div>" +
    (logData.log.truncated
      ? '<p class="app-block-sub">Viser de nyeste ' + rader.length +
        " linjene. Hele loggen ligger i filen.</p>"
      : "");
}

const BOLK_KLASSE = { 0: "is-0", 1: "is-1", 2: "is-2" };

function renderAfterTasks(view) {
  if (!view || !view.bolker.length) {
    el("after-list").innerHTML =
      tomtFelt("Ingenting å følge opp",
        "Oppfølging bygges fra logglinjene. Den fylles når noe blir stoppet, " +
        "når en felle går av, eller når et menneske har svart på et rødt varsel.");
    return;
  }
  el("after-note").textContent =
    view.antall + " saker, " + view.antall_oppgaver +
    " ting å gjøre. Bygget rett fra logglinjene. Det som haster står først.";

  el("after-list").innerHTML = view.bolker.map((bolk) =>
    '<section class="app-bolk ' + (BOLK_KLASSE[bolk.nivaa] || "") + '">' +
    '<h3 class="app-bolk-h">' + esc(bolk.navn) +
    '<span class="app-count is-quiet">' + bolk.saker.length + "</span></h3>" +
    bolk.saker.map((sak) => {
      const t = sak.topp;
      const topp = [t.agent, t.handling].filter(Boolean).join(" · ");
      const detalj = [t.belop, t.mottaker].filter(Boolean).join(" · ");
      return (
        '<article class="app-case">' +
        '<div class="app-case-top">' +
        "<div><strong>" + esc(topp) + "</strong>" +
        (detalj ? '<span class="app-case-detail">' + esc(detalj) + "</span>" : "") +
        "</div>" +
        (t.id
          ? '<span class="app-case-id">' + esc(lwName(t.id)) +
            '<span class="app-raw">' + esc(t.id) + "</span></span>"
          : "") +
        "</div>" +
        '<ul class="app-case-tasks">' +
        sak.oppgaver.map((o) =>
          '<li><span class="app-role">' + esc(ROLLE_VIS[o.rolle] || o.rolle) + "</span>" +
          '<span class="app-task-text">' + esc(o.tekst) + "</span></li>"
        ).join("") +
        "</ul></article>"
      );
    }).join("") +
    "</section>"
  ).join("") +
  '<p class="app-block-sub app-suggest">' +
  "<strong>Hvem og når er forslag.</strong> Eier er utledet av hva saken gjelder, " +
  "og rekkefølgen av hvor alvorlig utfallet var. Lonewatch har ingen kobling til " +
  "et oppgavesystem, ingen frister og ingen tildeling — ingenting her er sendt noe sted." +
  "</p>";
}

/* `vault/after.py` eier engelske rollekoder. Oversettelsen bor i ui/ fordi det
 * er visningstekst, og after_view.py har alt gjort den - dette er bare for
 * koder den ikke kjenner. */
const ROLLE_VIS = {
  security: "Sikkerhet", finance: "Økonomi", employee: "Den ansatte", it: "IT",
};

async function loadAfter() {
  /* Fersk sjekk hver gang Etter aapnes. Striper over tabellen er det foerste
   * et menneske leser her, og den skal gjelde loggen slik den er NAA - ikke
   * slik den var sist noen trykket paa en knapp. */
  await verifyQuietly();
  renderChainStrip();
  await hentTamperListe();
  renderTamperButtons();
  renderTamperResult();
  await hentLogg();
  renderLogTable();

  const data = await api("/api/after");
  if (!data.available) {
    el("after-note").textContent = data.note || "Etter-listen er ikke tilgjengelig.";
    el("after-list").innerHTML = '<p class="app-empty">Tom liste.</p>';
    return;
  }
  renderAfterTasks(data.view);
}

/* ---------------- Bryt loggen ----------------
 *
 * Fire knapper. Hver kjoerer ETT ekte angrep paa en KOPI av loggen og lar den
 * vanlige verifiseringen svare. All logikken ligger i vault/tamper_demo.py;
 * her tegnes svaret.
 *
 * Det viktigste valget: «full» (skriv om hele kjeden og signer et nytt anker)
 * blir IKKE roedt og blir IKKE kalt en feil. Den har `expected_detected=false`
 * fordi det er sant: den som har loggnoekkelen kan signere ankeret, og da er
 * en logg som er internt perfekt ikke til aa skille fra en ekte. Det er
 * grensen, og den staar i vault/LIMITS.md punkt 1 og 12. Aa farge den roed
 * ville vaert aa late som sjekken feilet; aa skjule den ville vaert verre.
 * Derfor staar den i sin egen, rolige ramme - med begge hashene ved siden av
 * hverandre, fordi det er NOEYAKTIG det som avsloerer angrepet hvis du har
 * skrevet ned den gamle hashen utenfor maskinen. */

let tamperListe = null;      // [{attack, title}] fra /api/tamper
let tamperKjorer = null;     // navnet paa angrepet som kjoerer naa
let tamperSvar = {};         // attack -> resultatet (hvilke som er kjoert)
let tamperSist = null;       // det ene resultatet som vises

/* Ett resultat av gangen, ikke en stabel.
 *
 * Fire kort under hverandre gjorde Etter-fanen 1531 px hoey paa 1440x900, og
 * da maa siden rulle. Rulling er ikke bare stygt her: «Bryt loggen» skal
 * leses ved siden av «Sjekk loggen» rett over, og de to kan ikke sammenlignes
 * hvis det ene er utenfor skjermen. Knappene viser hvilke som ER kjoert, saa
 * ingenting blir borte - man trykker igjen for aa se det. */

async function hentTamperListe() {
  if (tamperListe) return tamperListe;
  try {
    const r = await api("/api/tamper");
    tamperListe = r.attacks || [];
  } catch (e) {
    tamperListe = [];
  }
  return tamperListe;
}

function renderTamperButtons() {
  const boks = el("tamper-buttons");
  if (!boks) return;
  const liste = tamperListe || [];
  el("tamper-count").textContent = liste.length ? liste.length + " angrep" : "";
  boks.innerHTML = liste
    .map((a) => {
      const kjorer = tamperKjorer === a.attack;
      const gjort = Object.prototype.hasOwnProperty.call(tamperSvar, a.attack);
      return (
        '<button type="button" class="lw-btn lw-btn-quiet app-tamper-btn' +
        (gjort ? " is-done" : "") + '" data-tamper="' + esc(a.attack) + '"' +
        (tamperKjorer ? " disabled" : "") + ">" +
        '<span class="app-tamper-btn-name">' + esc(a.title) + "</span>" +
        '<span class="app-tamper-btn-state">' +
        (kjorer ? "kjører …" : gjort ? "kjørt" : "kjør") + "</span>" +
        "</button>"
      );
    })
    .join("");
}

/* Hashparet. Begge staar ved siden av hverandre, alltid, ogsaa naar de er
 * like: det er sammenligningen som er poenget, ikke det ene tallet. */
function hashPar(r) {
  const likt = r.head_hash_before === r.head_hash_after;
  return (
    '<div class="app-tamper-hashes">' +
    '<div class="app-tamper-hash"><dt>Siste hash før</dt>' +
    '<dd><code class="app-hash">' + esc(r.head_hash_before || "–") + "</code></dd></div>" +
    '<div class="app-tamper-hash' + (likt ? "" : " is-changed") + '">' +
    "<dt>Siste hash etter</dt>" +
    '<dd><code class="app-hash">' + esc(r.head_hash_after || "–") + "</code></dd></div>" +
    "</div>" +
    '<p class="app-note">' +
    (likt
      ? "Hashen står stille: angrepet traff en linje lenger inn i kjeden, og " +
        "sjekken peker den ut nedenfor."
      : "Hashen er en annen. Har du skrevet ned den gamle utenfor maskinen, " +
        "ser du avviket med øyet.") +
    "</p>"
  );
}

function renderTamperResult() {
  const boks = el("tamper-result");
  if (!boks) return;
  if (tamperKjorer) {
    boks.innerHTML =
      '<div class="app-tamper-card"><p class="app-note">Kjører angrepet på en ' +
      "kopi av loggen …</p></div>";
    return;
  }
  if (!tamperSist) {
    boks.innerHTML =
      '<p class="app-empty">Ingen angrep kjørt ennå. Trykk en av de fire over.</p>';
    return;
  }
  boks.innerHTML = [tamperSist]
    .map((n) => {
      const r = tamperSvar[n];
      if (r.error) {
        return (
          '<div class="app-tamper-card is-note"><h3>' + esc(n) + "</h3>" +
          '<p class="app-note">' + esc(r.error) + "</p></div>"
        );
      }
      /* Tre utfall, tre farger - og «grensen» er ikke en av de to andre.
       *   oppdaget og ventet:        gronn (sjekken gjorde jobben)
       *   ikke oppdaget og ventet:   rolig (den dokumenterte grensen)
       *   noe annet enn ventet:      rodt (da stemmer ikke dokumentasjonen) */
      const grense = r.expected_detected === false;
      const klasse = !r.as_documented
        ? "is-bad"
        : grense
        ? "is-limit"
        : "is-ok";
      const merke = !r.as_documented
        ? "ikke som dokumentert"
        : grense
        ? "grensen, sagt ærlig"
        : "oppdaget";
      return (
        '<div class="app-tamper-card ' + klasse + '">' +
        '<div class="app-tamper-head">' +
        "<h3>" + esc(r.title) + "</h3>" +
        '<span class="app-tamper-badge">' + esc(merke) + "</span>" +
        "</div>" +
        '<p class="app-tamper-did"><b>Dette gjorde vi</b> ' + esc(r.what_we_did) + "</p>" +
        '<dl class="app-tamper-facts">' +
        "<div><dt>Ble det oppdaget?</dt><dd>" +
        (r.detected ? "Ja" : "Nei") +
        (r.as_documented ? "" : " — og det var ikke ventet") +
        "</dd></div>" +
        "<div><dt>Linjer</dt><dd>" + esc(String(r.lines_before)) + " → " +
        esc(String(r.lines_after)) + "</dd></div>" +
        (r.broken_seq != null
          ? "<div><dt>Første brudd</dt><dd>#" + esc(String(r.broken_seq)) + "</dd></div>"
          : "") +
        "<div><dt>Den ekte loggen</dt><dd>" +
        (r.real_log_untouched
          ? "ikke rørt — samme navn, samme sha256, samme størrelse før og etter"
          : "ENDRET — dette er en feil i demoen") +
        "</dd></div>" +
        "</dl>" +
        hashPar(r) +
        '<p class="app-tamper-why">' +
        esc(r.explanation || r.verify_text || "").replace(/\n/g, "<br>") +
        "</p>" +
        "</div>"
      );
    })
    .join("");
}

async function kjorTamper(attack) {
  if (!krevOpplast("Å bryte loggen")) return;
  if (tamperKjorer) return;
  tamperKjorer = attack;
  renderTamperButtons();
  renderTamperResult();
  try {
    tamperSvar[attack] = await api("/api/tamper", { attack: attack });
  } catch (e) {
    /* 409 fra tamper_demo: demoen kan ikke kjoeres ærlig akkurat naa (tom
     * logg, for kort logg, eller en logg som ikke stemmer FOER vi begynner).
     * Det er ikke en feil i knappen, og teksten sier hvorfor. */
    tamperSvar[attack] = { error: e.message };
  } finally {
    tamperKjorer = null;
    tamperSist = attack;
  }
  renderTamperButtons();
  renderTamperResult();
}

/* ---------------- sjekk loggen ---------------- */

/* Kjoerer sjekken i bakgrunnen, uten aa vise banneret.
 *
 * Hvorfor i det hele tatt: ringen "Loggkjede" paa Oversikt staar som "Ikke
 * sjekket ennaa" til noen har kjoert sjekken, og det SKAL den - vi viser
 * aldri OK for noe vi ikke har sett paa. Men aa kreve at noen trykker en knapp
 * foer ringen kan si noe, gjoer at den staar tom gjennom hele demoen.
 *
 * Dette er den ekte sjekken: samme /api/verify, samme lesing og dekryptering
 * av hele filen fra disk. Den er bare ikke utloest av et klikk. */
async function verifyQuietly() {
  try {
    const r = await api("/api/verify");
    if (latest && latest.log) {
      latest.log.last_verify = r;
      latest.log.lines = r.lines;
      /* Svaret gjelder akkurat de linjene det nettopp leste. */
      latest.log.verify_stale = false;
    }
    if (activeTab === "overview") await refreshOverview();
    return r;
  } catch (e) {
    /* Feiler den, lar vi ringen staa som "Ikke sjekket ennaa". Det er riktig:
     * vi vet ikke om loggen stemmer. */
    return null;
  }
}

async function verify() {
  const r = await api("/api/verify");
  const b = el("verify-banner");
  b.classList.remove("hidden");
  b.classList.toggle("is-bad", !r.ok);
  b.textContent = r.text;
  if (latest) {
    latest.log.last_verify = r;
    latest.log.lines = r.lines;
    latest.log.verify_stale = false;
  }
  /* Ringen "Loggkjede" paa Oversikt staar som "Ikke sjekket ennaa" til noen
   * faktisk har sjekket. Naa har de det. */
  if (activeTab === "overview") refreshOverview();
  if (activeTab === "after") loadAfter();
}

/* ---------------- hendelser fra brukeren ---------------- */

document.addEventListener("input", (ev) => {
  const id = ev.target.getAttribute && ev.target.getAttribute("data-amt");
  if (!id) return;
  typed[id] = ev.target.value;
  // Tegn bare knappen om, slik at feltet ikke mister markøren.
  const card = (latest.waiting || []).find((c) => c.request.id === id);
  if (!card) return;
  const ok = amountMatches(typed[id], card.request.amount);
  const btn = document.querySelector('[data-approve="' + id + '"]');
  if (btn) btn.disabled = !ok;
  const hint = ev.target.parentElement.querySelector(".app-hint");
  if (hint) {
    hint.className = "app-hint" + (ok ? " is-ok" : "");
    hint.textContent = ok ? "Stemmer." : "Skriv beløpet nøyaktig for å kunne godkjenne.";
  }
});

document.addEventListener("click", async (ev) => {
  const t = ev.target;
  if (!t.getAttribute) return;

  /* «Bryt loggen». Knappen har tekst i to spenn, saa klikket kan treffe et
   * barn - derfor closest() og ikke bare target. */
  const tamperKnapp = t.closest && t.closest("[data-tamper]");
  if (tamperKnapp) {
    await kjorTamper(tamperKnapp.getAttribute("data-tamper"));
    return;
  }

  const approve = t.getAttribute("data-approve");
  const reject = t.getAttribute("data-reject");
  if (approve || reject) {
    const id = approve || reject;
    /* Betenkningstiden sendes IKKE herfra lenger. Tjeneren maaler den selv,
     * fra kortet ble lagt i koeen - et tall nettleseren oppgir er ikke en
     * maaling, det er en paastand. Se H2 i docs/ANGREP.md. */
    let out;
    try {
      out = await api("/api/respond", {
        request_id: id,
        approved: Boolean(approve),
        typed_amount: typed[id] || null,
      });
    } catch (e) {
      /* 403: noekkelen holdt ikke (eller mangler). 503: laasen er ikke satt
       * opp. Begge betyr at INGENTING ble godkjent, og det skal staa paa
       * skjermen - ikke bare i konsollen. */
      if (e.status === 403 || e.status === 503) {
        menneskeOk = false;
        menneskePseudonym = null;
        if (e.status === 403) settMenneskeNokkel("");
        tegnLaas(e.status === 503 ? "av" : "laast", e.message);
        showTab("queue");
      } else {
        tegnLaas("feil", e.message);
      }
      return;
    }
    delete typed[id];
    apply(out.state);
    if (activeTab === "after") loadAfter();
    return;
  }

  const pick = t.closest ? t.closest("[data-pick]") : null;
  if (pick) {
    valgt = pick.getAttribute("data-pick");
    renderQueue();
    return;
  }

  const pack = t.closest ? t.closest("[data-pack]") : null;
  if (pack) {
    valgtPakke = pack.getAttribute("data-pack");
    renderBefore(latest.before);
    return;
  }

  const lf = t.getAttribute("data-logfilter");
  if (lf) {
    logFilter = lf;
    renderLogTable();
    return;
  }

  if (t.getAttribute("data-empty-story")) {
    storyPlay();
    return;
  }

  const lim = t.getAttribute("data-limits");
  if (lim) {
    visLimits(lim);
    return;
  }

  const tab = t.closest ? t.closest("[data-tab]") : null;
  if (tab) showTab(tab.getAttribute("data-tab"));
});

/* ---------------- bevegelse ----------------
 *
 * Alt som beveger seg spoer her foerst. Den som har bedt operativsystemet om
 * mindre bevegelse, skal faa sluttilstanden med en gang - ikke en kortere
 * animasjon. Vi leser innstillingen hver gang, slik at den virker uten at
 * siden lastes paa nytt.
 */
function roligBevegelse() {
  try {
    return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  } catch (e) {
    return false;
  }
}

/* Tall som teller opp fra forrige verdi til den nye.
 *
 * Fra FORRIGE verdi, ikke fra null: naar stroemmen gaar og 39 blir 40, skal
 * tallet flytte seg ett hakk - ikke rulle gjennom hele skalaen paa nytt hvert
 * annet sekund. Foerste gang er forrige verdi null, og da teller den opp. */
const tellTilstand = new WeakMap();

function tellOpp(node, til) {
  if (typeof til !== "number" || !isFinite(til)) {
    node.textContent = "–";
    tellTilstand.delete(node);
    return;
  }
  const fra = tellTilstand.get(node);
  tellTilstand.set(node, til);

  if (fra === til) return;
  if (roligBevegelse() || fra === undefined && til === 0) {
    node.textContent = dashNum(til);
    return;
  }

  const start = typeof fra === "number" ? fra : 0;
  const t0 = performance.now();
  const lengde = Math.min(900, 220 + Math.abs(til - start) * 18);

  function steg(naa) {
    const p = Math.min(1, (naa - t0) / lengde);
    // Mykt ut: raskt i starten, roer seg mot slutten.
    const e = 1 - Math.pow(1 - p, 3);
    node.textContent = dashNum(Math.round(start + (til - start) * e));
    if (p < 1) requestAnimationFrame(steg);
    else node.textContent = dashNum(til);
  }
  requestAnimationFrame(steg);
}

/* Tallene i Agentaktivitet tegnes av designsystemets StatCard, som setter
 * teksten selv. Vi lar den gjoere det, og teller opp etterpaa - da er
 * sluttverdien alltid den React skrev, ogsaa hvis animasjonen avbrytes. */
function animerTall() {
  if (!dashboardData) return;
  const n = dashboardData.counts || {};
  const verdier = [n.evaluated, n.red, n.blocked];
  document.querySelectorAll("#dashboard-root .lw-stat-value").forEach((node, i) => {
    tellOpp(node, typeof verdier[i] === "number" ? verdier[i] : null);
  });
}

const VIEW_SUB = {
  overview: "Nordlys Forsikring · simulering",
  before: "Tillegg testes i en lukket boks før de slipper inn",
  queue: "Røde varsler som bare et menneske kan svare på",
  after: "Den låste loggen, og hva som må følges opp",
  custom: "Din egen forespørsel, gjennom samme vei som demoen",
};

const VIEW_HASH = {
  overview: "#", before: "#foer", queue: "#godkjenning",
  after: "#etter", custom: "#prov",
};

function showTab(tab) {
  if (!VIEW_HASH[tab]) tab = "overview";
  activeTab = tab;
  /* CSS leser fanen herfra (se «Ikke si det samme to ganger» i style.css). */
  document.body.dataset.tab = tab;

  document.querySelectorAll("#app-nav [data-tab]").forEach((b) =>
    b.classList.toggle("is-active", b.getAttribute("data-tab") === tab)
  );

  const view = VIEWS.find((v) => v.tab === tab);
  el("app-view-title").textContent = view ? view.navn : "Oversikt";
  document.querySelector(".app-sub").textContent = VIEW_SUB[tab];

  ["overview", "before", "queue", "after", "custom"].forEach((t) =>
    el("tab-" + t).classList.toggle("hidden", t !== tab)
  );

  if (history.replaceState) history.replaceState(null, "", VIEW_HASH[tab]);
  /* Banneret foelger fanen: det staar ikke paa «Prøv selv». Se
   * LAAST_BANNER_FANER. */
  renderLaastSide();

  if (tab === "after") loadAfter();
  if (tab === "custom") loadCustomHelp();
  if (tab === "overview") refreshOverview();
  if (tab === "queue") hentLogg();
}

/* ---------------- begrensninger ----------------
 *
 * Raa filstier hoerer ikke hjemme i broedteksten. Teksten her er et sammendrag
 * av det som staar i filene, og filnavnet staar nederst for den som vil lese
 * hele. Ingenting her er generert - det er skrevet av hand fra LIMITS-filene.
 */
const LIMITS = {
  sandkassen: {
    tittel: "Hva sandkassen ikke klarer",
    punkter: [
      "Den er ikke isolasjon. Tillegget kjører i en egen prosess på samme maskin, uten container og uten egen bruker.",
      "«Rent» betyr bare at vi ikke så noe denne gangen. Et tillegg som venter, eller som bare gjør skade når det er i drift, ser rent ut her.",
      "Et tillegg som krasjer rapporteres i dag som rent. Vi fikk ingen observasjon, men verdiktet sier ikke det.",
      "Den kjører bare tillegg den har en fil for fra før. Et ukjent navn gir «ikke testet» — ingenting lastes ned.",
      "Nettverk er alltid nei. Vi ser hvilken adresse tillegget prøvde på, ikke hva det ville sendt.",
    ],
    fil: "sandbox/LIMITS.md",
  },
  loggen: {
    tittel: "Hva loggen ikke klarer",
    punkter: [
      "I demoen ligger loggen i minnet og i én fil ved siden av. Det finnes ingen oppbevaringstid, ingen replikering og ingen ekstern kopi.",
      "Hash-kjeden fanger endring og fjerning inne i loggen, og hale-ankeret fanger kutting av de siste linjene. Den som har både loggen, ankeret og nøkkelen kan likevel skrive den om fra et punkt.",
      "Mistes nøkkelen, er loggen uleselig. Det finnes ingen reservenøkkel og ingen rotasjon.",
      "Loggen kan ikke bevise hvem som skrev en linje. Fernet har én delt nøkkel, ingen signatur per skribent.",
      "Dataminimering gjør loggen mindre identifiserende, ikke anonym. Beløp, tidspunkt og agent står i klartekst.",
      "Ingen logg over hvem som har lest loggen.",
    ],
    fil: "vault/LIMITS.md og docs/PERSONVERN.md",
  },
};

function visLimits(navn) {
  const l = LIMITS[navn];
  if (!l) return;
  el("limits-title").textContent = l.tittel;
  el("limits-body").innerHTML =
    "<ul>" + l.punkter.map((x) => "<li>" + esc(x) + "</li>").join("") + "</ul>" +
    '<p class="app-block-sub">Hele teksten står i <code>' + esc(l.fil) + "</code>.</p>";
  el("limits-dialog").classList.remove("hidden");
  el("limits-close").focus();
}

function lukkLimits() {
  el("limits-dialog").classList.add("hidden");
}

el("limits-close").addEventListener("click", lukkLimits);
el("limits-dialog").addEventListener("click", (ev) => {
  if (ev.target === el("limits-dialog")) lukkLimits();
});
document.addEventListener("keydown", (ev) => {
  if (ev.key === "Escape") lukkLimits();
});

/* ---------------- presentasjonsmodus ----------------
 *
 * Appen vises paa projektor. Da er 13 px broedtekst uleselig fra fjerde rad,
 * og fotnoter, begrensningslenker og raa IDer er stoey ingen i salen kan gjoere
 * noe med.
 *
 * Modusen SKJULER bare - den endrer ingen tall og slaar ingenting av.
 * Beloepsporten, reglene og loggen er de samme. Det som forsvinner er tekst
 * som bare gir mening naar man sitter foran skjermen selv.
 */
const PRESENT_NOKKEL = "lonewatch:presentasjon";

function settPresentasjon(paa) {
  document.querySelector(".lw").classList.toggle("is-present", paa);
  const knapp = el("btn-present");
  knapp.setAttribute("aria-pressed", paa ? "true" : "false");
  knapp.classList.toggle("is-on", paa);
  try {
    localStorage.setItem(PRESENT_NOKKEL, paa ? "1" : "0");
  } catch (e) {
    /* Privat vindu eller blokkert lagring: modusen virker, den huskes bare ikke. */
  }
}

el("btn-present").addEventListener("click", () => {
  settPresentasjon(el("btn-present").getAttribute("aria-pressed") !== "true");
});

el("btn-bell").addEventListener("click", () => showTab("queue"));

/* Laas opp og laas igjen. Noekkelen sjekkes mot tjeneren med én gang, slik at
 * ingen staar og tror de er innlogget til de proever aa godkjenne noe. */
el("human-form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const verdi = el("human-key").value.trim();
  if (!verdi) {
    tegnLaas("laast", "Skriv inn nøkkelen.");
    return;
  }
  settMenneskeNokkel(verdi);
  await sjekkMenneskeNokkel();
  if (!menneskeOk) el("human-key").focus();
  /* Tilstanden vi alt har, er den MINIMERTE: den har ingen summary, ingen
   * regelnavn og en maskert mottaker. Naa som noekkelen holder, henter vi hele
   * saken paa nytt, og slipper stroemmen i gang. Uten dette ville siden
   * staatt med maskerte kort til neste gang noe annet oppdaterte den. */
  if (menneskeOk) {
    el("verify-banner").classList.add("hidden");
    apply(await api("/api/state"));
    await verifyQuietly();
    startFeed();
  }
  if (activeTab === "queue") renderQueueDetail();
});

el("human-logout").addEventListener("click", async () => {
  settMenneskeNokkel("");
  menneskeOk = false;
  menneskePseudonym = null;
  stopFeed();
  stopStory();
  await sjekkMenneskeNokkel();
  /* Og tilbake til det minimerte synet. Hele poenget med aa logge ut er at
   * det som sto paa skjermen ikke skal staa der etterpaa. */
  apply(await api("/api/state"));
  if (activeTab === "queue") renderQueueDetail();
});

el("custom-form").addEventListener("submit", sendCustom);
el("c-action").addEventListener("change", syncCustomFields);
el("btn-verify").addEventListener("click", verify);
el("btn-story").addEventListener("click", storyPlay);
el("btn-story-next").addEventListener("click", storyNext);
el("btn-reset").addEventListener("click", async () => {
  if (!krevOpplast("Å nullstille demoen")) return;
  stopStory();
  typed = {};
  shownAt = {};
  waitingSig = null;
  el("verify-banner").classList.add("hidden");
  el("story-band").classList.add("hidden");
  dashboardData = null;
  apply(await api("/api/reset", {}));
  /* Ny, tom logg. Sjekken kjoeres paa nytt, saa ringen ikke viser et svar som
   * gjaldt loggen fra foer nullstillingen. */
  await verifyQuietly();
  if (activeTab === "overview") await refreshOverview();
  startFeed();
});

/* ---------------- start ---------------- */

/* Adressen er en del av navigasjonen, ikke bare et spor etter den: fanen staar
 * i hash-en, saa tilbakeknappen og en delt lenke virker. */
const TAB_FRA_HASH = {
  "#etter": "after", "#foer": "before", "#prov": "custom", "#godkjenning": "queue",
};

function tabFraAdressen() {
  return TAB_FRA_HASH[location.hash] || "overview";
}

window.addEventListener("hashchange", () => {
  const onsket = tabFraAdressen();
  if (onsket !== activeTab) showTab(onsket);
});

(async () => {
  buildNav();
  try {
    if (localStorage.getItem(PRESENT_NOKKEL) === "1") settPresentasjon(true);
  } catch (e) {
    /* ingen lagring tilgjengelig - start i vanlig modus */
  }
  /* Laasen foerst. Da er knappene i koeen riktige fra foerste tegning, og
   * ingen ser en Godkjenn-knapp som ikke ville virket. */
  await sjekkMenneskeNokkel();
  apply(await api("/api/state"));
  showTab(tabFraAdressen());
  /* Sjekk loggen med én gang siden aapnes, saa ringen viser OK og de tolv
   * foerste tegnene av siste hash uten at noen maa trykke paa noe. */
  await verifyQuietly();
  startFeed();
})();
