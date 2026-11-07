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

const digits = (s) => String(s || "").replace(/[^0-9]/g, "");
const kroner = (n) =>
  n == null ? "" : Math.round(n).toLocaleString("nb-NO").replace(/ /g, " ") + " kr";

/* Norsk tekst for regelnavnene fra gateway. Ukjente navn vises som de er,
   slik at nye regler aldri blir usynlige. */
const RULE_TEXT = {
  unknown_recipient: "ukjent mottaker",
  amount_over_limit: "over beløpsgrensen",
  irreversible: "kan ikke angres",
  personal_data_external: "personopplysninger ut av huset",
  new_package: "ukjent tillegg",
};

let latest = null;
let waitingSig = null;   // hindrer at køen tegnes om mens noen skriver i den
let feedTimer = null;
let storyTimer = null;
let typed = {};          // request_id -> det brukeren har skrevet
let shownAt = {};        // request_id -> når kortet kom på skjermen
let activeTab = "queue";

/* ---------------- nettverk ---------------- */

async function api(path, body) {
  const res = await fetch(path, {
    method: body === undefined ? "GET" : "POST",
    headers: body === undefined ? {} : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!res.ok) throw new Error(path + " svarte " + res.status);
  return res.json();
}

/* ---------------- den rolige strømmen ---------------- */

function startFeed() {
  stopFeed();
  feedTimer = setInterval(async () => {
    if (latest && latest.feed && latest.feed.done) return stopFeed();
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
  stopStory();
  const out = await api("/api/story/step", {});
  apply(out.state);
  if (out.story.done) el("story-band").classList.remove("live");
}

/* ---------------- tegning ---------------- */

function apply(state) {
  latest = state;
  render();
}

function render() {
  if (!latest) return;
  renderStory(latest.story);
  renderWaiting(latest.waiting);
  renderBlocked(latest.blocked);
  renderAnswered(latest.answered);
  renderCalm(latest.calm, latest.calm_total);
  renderNotices(latest.notices);
  renderBefore(latest.before);

  document.body.classList.toggle("alert", latest.waiting.length > 0);

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

function chips(decision) {
  const parts = (decision.reasons || []).map(
    (r) => '<span class="chip">' + esc(RULE_TEXT[r] || r) + "</span>"
  );
  parts.push('<span class="chip quiet">risiko: ' + esc(decision.risk) + "</span>");
  return '<div class="chips">' + parts.join("") + "</div>";
}

function who(card) {
  const r = card.request;
  const bits = [
    '<span class="agent">' + esc(card.agent_label) + "</span>",
    esc(card.action_label),
  ];
  if (r.recipient) bits.push("til " + esc(r.recipient));
  if (card.source === "story") bits.push("hendelsen");
  return '<div class="who">' + bits.join(' <span class="sep">&middot;</span> ') + "</div>";
}

function renderWaiting(list) {
  const badge = el("waiting-count");
  badge.textContent = list.length;
  badge.classList.toggle("zero", list.length === 0);

  /* Tegn bare om når køen faktisk er endret. Den rolige strømmen oppdaterer
     siden hvert par sekund, og uten dette ville beløpsfeltet mistet markøren
     midt i at noen skriver. */
  const sig = JSON.stringify(list.map((c) => [c.request.id, c.status, c.error]));
  if (sig === waitingSig) return;
  waitingSig = sig;

  if (!list.length) {
    el("waiting").innerHTML = '<p class="empty">Ingenting venter. Agentene jobber.</p>';
    return;
  }

  const focused = document.activeElement;
  const refocus = focused && focused.getAttribute ? focused.getAttribute("data-amt") : null;
  const caret = refocus ? focused.selectionStart : null;

  el("waiting").innerHTML = list
    .map((card) => {
      const r = card.request;
      const d = card.decision;
      if (!shownAt[r.id]) shownAt[r.id] = Date.now();

      let gate;
      if (d.requires_typed_amount) {
        const val = typed[r.id] || "";
        const ok = digits(val) !== "" && Number(digits(val)) === Math.round(r.amount);
        const hint = card.error
          ? '<span class="hint bad">' + esc(card.error) + "</span>"
          : ok
          ? '<span class="hint ok">Stemmer.</span>'
          : '<span class="hint">Skriv beløpet nøyaktig for å kunne godkjenne.</span>';
        gate =
          '<div class="gate"><label for="amt-' + esc(r.id) + '">Skriv beløpet for å godkjenne</label>' +
          '<div class="gate-row">' +
          '<input id="amt-' + esc(r.id) + '" inputmode="numeric" autocomplete="off" ' +
          'placeholder="0" value="' + esc(val) + '" data-amt="' + esc(r.id) + '">' +
          '<button class="danger" data-approve="' + esc(r.id) + '"' + (ok ? "" : " disabled") + ">Godkjenn</button>" +
          '<button data-reject="' + esc(r.id) + '">Avvis</button>' +
          hint +
          "</div></div>";
      } else {
        gate =
          '<div class="gate"><div class="gate-row">' +
          '<button class="danger" data-approve="' + esc(r.id) + '">Godkjenn</button>' +
          '<button data-reject="' + esc(r.id) + '">Avvis</button>' +
          (card.error ? '<span class="hint bad">' + esc(card.error) + "</span>" : "") +
          "</div></div>";
      }

      return (
        '<article class="red-card">' +
        who(card) +
        '<p class="consequence">' + esc(d.consequence_text) + "</p>" +
        chips(d) +
        '<p class="said"><b>Agenten sier</b>' + esc(r.summary) + "</p>" +
        gate +
        "</article>"
      );
    })
    .join("");

  if (refocus) {
    const again = document.querySelector('[data-amt="' + refocus + '"]');
    if (again) {
      again.focus();
      if (caret != null) again.setSelectionRange(caret, caret);
    }
  }
}

function renderBlocked(list) {
  el("blocked-wrap").classList.toggle("hidden", !list.length);
  el("blocked").innerHTML = list
    .map(
      (card) =>
        '<div class="flat-card stopped"><div class="line1">' +
        '<span class="agent">' + esc(card.agent_label) + "</span>" +
        '<span class="muted">' + esc(card.action_label) + "</span></div>" +
        '<div class="line2">' + esc(card.decision.consequence_text) + "</div></div>"
    )
    .join("");
}

function renderAnswered(list) {
  el("answered-wrap").classList.toggle("hidden", !list.length);
  el("answered").innerHTML = list
    .map((card) => {
      const ok = card.status === "approved";
      const h = card.human || {};
      const svar = ok ? "Godkjent" : "Avvist";
      const extra =
        (h.employee_pseudonym ? " av " + esc(h.employee_pseudonym) : "") +
        (h.seconds_to_decide != null
          ? " etter " + Math.round(h.seconds_to_decide) + " s"
          : "") +
        (ok && h.typed_amount != null ? ", skrev " + esc(kroner(h.typed_amount)) : "");
      return (
        '<div class="flat-card ' + (ok ? "ok-answer" : "no-answer") + '"><div class="line1">' +
        '<span class="agent">' + esc(svar) + "</span>" +
        '<span class="muted">' + esc(card.agent_label) + " &middot; " + esc(card.action_label) + "</span>" +
        "</div>" +
        '<div class="line2">' + esc(card.decision.consequence_text) + extra + "</div></div>"
      );
    })
    .join("");
}

function renderCalm(list, total) {
  const badge = el("calm-count");
  badge.textContent = total;
  if (!list.length) {
    el("calm").innerHTML = '<p class="empty">Ingenting ennå.</p>';
    return;
  }
  el("calm").innerHTML = list
    .map(
      (card) =>
        '<div class="calm-row"><span class="tick">&#9679;</span>' +
        '<span class="agent">' + esc(card.agent_label) + "</span>" +
        '<span class="what">' + esc(card.request.summary) + "</span></div>"
    )
    .join("");
}

function renderNotices(list) {
  if (!list || !list.length) {
    el("notices").innerHTML = '<p class="empty">Ingen feller har gått av.</p>';
    return;
  }
  el("notices").innerHTML = list
    .map(
      (n) =>
        '<div class="notice"><span class="nt">' + esc(n.title) + "</span>" +
        '<span class="nd">' + esc(n.detail) + "</span></div>"
    )
    .join("");
}

/* ---------------- Før: sandkassen ---------------- */

function renderBefore(b) {
  const box = el("before-list");
  if (!b) return;
  const rows = [];

  if (b.error) {
    rows.push(
      '<div class="after-row"><span class="box"></span><div>' +
        '<div class="at">Sandkassen svarte ikke</div>' +
        '<div class="ad">' + esc(b.error) + "</div></div>" +
        '<span class="ao">it</span></div>'
    );
  }

  b.scanned.forEach((r) => {
    const blocked = r.verdict === "blocked";
    rows.push(
      '<div class="after-row"><span class="box"></span><div>' +
        '<div class="at">' +
        esc(r.package_name) +
        " &middot; " +
        (blocked ? "stoppet i sandkassen" : "ingenting mistenkelig") +
        "</div>" +
        '<div class="ad">' +
        esc(r.notes) +
        (r.destinations && r.destinations.length
          ? " Adresser: " + esc(r.destinations.join(", ")) + "."
          : "") +
        "</div></div>" +
        '<span class="ao">' + (blocked ? "blokkert" : "rent") + "</span></div>"
    );
  });

  b.untested.forEach((u) => {
    rows.push(
      '<div class="after-row"><span class="box"></span><div>' +
        '<div class="at">' + esc(u.package_name) + " &middot; ikke testet</div>" +
        '<div class="ad">' + esc(u.note) + "</div></div>" +
        '<span class="ao">ukjent</span></div>'
    );
  });

  box.innerHTML = rows.length
    ? rows.join("")
    : '<p class="empty">Ingen tillegg er forsøkt installert ennå.</p>';
}

/* ---------------- Etter ---------------- */

async function loadAfter() {
  const data = await api("/api/after");
  if (!data.available) {
    el("after-note").textContent =
      data.note === "kommer"
        ? "Etter-listen bygges av vault.after.build_after_actions. " +
          "Den er ikke på plass ennå: kommer."
        : data.note;
    el("after-list").innerHTML = '<p class="empty">Tom liste.</p>';
    return;
  }
  el("after-note").textContent = "Hva som må gjøres når noe har skjedd.";
  if (!data.items.length) {
    el("after-list").innerHTML =
      '<p class="empty">Ingenting å følge opp. Ingen røde forespørsler er behandlet.</p>';
    return;
  }
  el("after-list").innerHTML = data.items
    .map(
      (a) =>
        '<div class="after-row' + (a.done ? " done" : "") + '"><span class="box"></span>' +
        '<div><div class="at">' + esc(a.title) + "</div>" +
        '<div class="ad">' + esc(a.detail) + "</div></div>" +
        '<span class="ao">' + esc(a.owner_role) + "</span></div>"
    )
    .join("");
}

/* ---------------- sjekk loggen ---------------- */

async function verify() {
  const r = await api("/api/verify");
  const b = el("verify-banner");
  b.classList.remove("hidden");
  b.classList.toggle("bad", !r.ok);
  b.textContent = r.text;
  if (latest) {
    latest.log.last_verify = r;
    latest.log.lines = r.lines;
  }
}

/* ---------------- hendelser fra brukeren ---------------- */

document.addEventListener("input", (ev) => {
  const id = ev.target.getAttribute && ev.target.getAttribute("data-amt");
  if (!id) return;
  typed[id] = ev.target.value;
  // Tegn bare knappen om, slik at feltet ikke mister markøren.
  const card = (latest.waiting || []).find((c) => c.request.id === id);
  if (!card) return;
  const ok = Number(digits(typed[id])) === Math.round(card.request.amount) && digits(typed[id]) !== "";
  const btn = document.querySelector('[data-approve="' + id + '"]');
  if (btn) btn.disabled = !ok;
  const hint = ev.target.parentElement.querySelector(".hint");
  if (hint) {
    hint.className = "hint" + (ok ? " ok" : "");
    hint.textContent = ok ? "Stemmer." : "Skriv beløpet nøyaktig for å kunne godkjenne.";
  }
});

document.addEventListener("click", async (ev) => {
  const t = ev.target;
  if (!t.getAttribute) return;

  const approve = t.getAttribute("data-approve");
  const reject = t.getAttribute("data-reject");
  if (approve || reject) {
    const id = approve || reject;
    const started = shownAt[id] || Date.now();
    const out = await api("/api/respond", {
      request_id: id,
      approved: Boolean(approve),
      typed_amount: typed[id] || null,
      seconds_to_decide: (Date.now() - started) / 1000,
    });
    delete typed[id];
    apply(out.state);
    if (activeTab === "after") loadAfter();
    return;
  }

  const tab = t.getAttribute("data-tab");
  if (tab) showTab(tab);
});

function showTab(tab) {
  activeTab = tab;
  document.querySelectorAll(".tab-btn").forEach((b) =>
    b.classList.toggle("on", b.getAttribute("data-tab") === tab)
  );
  el("tab-before").classList.toggle("hidden", tab !== "before");
  el("tab-queue").classList.toggle("hidden", tab !== "queue");
  el("tab-after").classList.toggle("hidden", tab !== "after");
  const hash = tab === "after" ? "#etter" : tab === "before" ? "#foer" : "#";
  if (history.replaceState) history.replaceState(null, "", hash);
  if (tab === "after") loadAfter();
}

el("btn-verify").addEventListener("click", verify);
el("btn-story").addEventListener("click", storyPlay);
el("btn-story-next").addEventListener("click", storyNext);
el("btn-reset").addEventListener("click", async () => {
  stopStory();
  typed = {};
  shownAt = {};
  waitingSig = null;
  el("verify-banner").classList.add("hidden");
  el("story-band").classList.add("hidden");
  apply(await api("/api/reset", {}));
  startFeed();
});

/* ---------------- start ---------------- */

(async () => {
  apply(await api("/api/state"));
  if (location.hash === "#etter") showTab("after");
  if (location.hash === "#foer") showTab("before");
  startFeed();
})();
