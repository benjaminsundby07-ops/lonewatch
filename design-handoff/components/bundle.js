/* @ds-bundle: {"format":4,"namespace":"Lonewatch","components":[{"name":"Dashboard"},{"name":"Sidebar"},{"name":"LanguageToggle"},{"name":"PromoCard"},{"name":"Button"},{"name":"Panel"},{"name":"StatCard"},{"name":"ProgressStat"},{"name":"AgentTable"},{"name":"StatusRing"},{"name":"StatusRows"},{"name":"ExampleTag"},{"name":"GlassObject"}]} */
(function () {
  var React = window.React;
  var h = React.createElement;
  var uid = 0;
  function useId(prefix) {
    var ref = React.useRef(null);
    if (ref.current === null) { uid += 1; ref.current = prefix + uid; }
    return ref.current;
  }
  function cx() { return Array.prototype.filter.call(arguments, Boolean).join(' '); }

  /* =====================================================================
   * DATASETT. Alle tall og all tekst oversikten viser, ligger her og bare her.
   * Komponentene under tegner fra dette objektet. Bytt det ut med ekte data
   * fra backend (Lonewatch.setData eller prop `data` på Dashboard) uten å røre
   * designet. Tallene nå er EKSEMPELDATA, og grensesnittet merker dem slik så
   * lenge `isExample` er true.
   * ===================================================================== */
  var LONEWATCH_DATA = {
    isExample: true,
    defaultLang: 'no',
    counts: {
      evaluated: 40,        // Handlinger vurdert
      red: 7,               // Røde varsler
      blocked: 1,           // Blokkert
      allowed: 32,          // Sluppet gjennom
      waitingForHuman: 1,   // Røde varsler som venter på menneske
      followedUp: 6         // Fulgt opp
    },
    agents: [
      { id: 'customer_service', name: { no: 'Kundeservice', en: 'Customer service' }, actions: 9, red: 2, blocked: 0, allowed: 7 },
      { id: 'procurement', name: { no: 'Innkjøp', en: 'Procurement' }, actions: 8, red: 1, blocked: 0, allowed: 7 },
      { id: 'finance', name: { no: 'Økonomi', en: 'Finance' }, actions: 9, red: 2, blocked: 0, allowed: 7 },
      { id: 'hr', name: { no: 'HR', en: 'HR' }, actions: 7, red: 1, blocked: 0, allowed: 6 },
      { id: 'it_helper', name: { no: 'IT-hjelp', en: 'IT help' }, actions: 7, red: 1, blocked: 1, allowed: 5 }
    ],
    logChain: { status: 'ok', checkedAt: '2026-11-07T09:10:00Z' },   // status: 'ok' | 'broken' | null (ikke sjekket)
    sandbox: { tested: 2, blocked: 1 },
    log: { status: 'ok' },                                           // status: 'ok' | 'broken' | null
    // Formen på de små kurvene i de tre kortene. Ren pynt uten akser eller verdier,
    // men de er også eksempeldata og bør byttes mot ekte forløp eller fjernes.
    chartShapes: [
      { data: [52, 60, 66, 58, 63, 44, 40, 52, 36, 48, 58, 66, 54, 62], ghost: [40, 46, 50, 56, 50, 44, 50, 56, 60, 52, 48, 54, 58, 50], marks: [5, 8] },
      { data: [30, 64, 50, 44, 52, 40, 38, 48, 36, 30, 42, 34, 46, 54], ghost: [24, 40, 56, 48, 36, 44, 52, 42, 34, 40, 46, 40, 36, 44], marks: [4, 8] },
      { data: [44, 52, 60, 54, 50, 62, 54, 46, 40, 34, 44, 50, 42, 36], ghost: [36, 44, 46, 50, 56, 52, 46, 50, 42, 40, 46, 40, 48, 52], marks: [5, 9] }
    ],
    text: {
      no: {
        exampleTag: 'Eksempeldata',
        nav: ['Oversikt', 'Før', 'Under', 'Etter', 'Prøv selv'], alerts: 'Varsler', account: 'Konto', language: 'Språk',
        promoTitle: 'Send din egen forespørsel',
        promoText: 'Skriv en forespørsel og se den gå gjennom de samme reglene som demoen. Ingenting er avgjort på forhånd.',
        promoCta: 'Prøv selv',
        activity: 'Agentaktivitet', range: 'I dag',
        stats: ['Handlinger vurdert', 'Røde varsler', 'Blokkert'],
        allowed: 'Sluppet gjennom',
        waiting: 'Røde varsler som venter på menneske', followed: 'Fulgt opp', of: 'av',
        table: 'Agenter', viewAll: 'Se alle',
        cols: ['Agent', 'Handlinger', 'Røde', 'Blokkert', 'Sluppet gjennom'],
        logChain: 'Loggkjede', logChainSub: 'Sjekk av logg', lastChecked: 'Sist sjekket:', notChecked: 'Ikke sjekket ennå',
        status: { ok: 'OK', broken: 'Feil', none: '–' },
        sandboxRow: 'Sandkasse', logRow: 'Logg',
        sandboxStatus: '{tested} testet, {blocked} blokkert'
      },
      en: {
        exampleTag: 'Example data',
        nav: ['Overview', 'Before', 'During', 'After', 'Try it yourself'], alerts: 'Alerts', account: 'Account', language: 'Language',
        promoTitle: 'Send your own request',
        promoText: 'Write a request and watch it go through the same rules as the demo. Nothing is decided in advance.',
        promoCta: 'Try it yourself',
        activity: 'Agent activity', range: 'Today',
        stats: ['Actions evaluated', 'Red alerts', 'Blocked'],
        allowed: 'Let through',
        waiting: 'Red alerts waiting for a human', followed: 'Followed up', of: 'of',
        table: 'Agents', viewAll: 'View all',
        cols: ['Agent', 'Actions', 'Red', 'Blocked', 'Let through'],
        logChain: 'Log chain', logChainSub: 'Log check', lastChecked: 'Last checked:', notChecked: 'Not checked yet',
        status: { ok: 'OK', broken: 'Broken', none: '–' },
        sandboxRow: 'Sandbox', logRow: 'Log',
        sandboxStatus: '{tested} tested, {blocked} blocked'
      }
    }
  };

  function isNum(n) { return typeof n === 'number' && isFinite(n); }
  function fmtNum(n, lang, digits) {
    if (!isNum(n)) return '–';
    return new Intl.NumberFormat(lang === 'en' ? 'en-US' : 'nb-NO', { minimumFractionDigits: digits || 0, maximumFractionDigits: digits || 0 }).format(n);
  }
  function fmtTime(iso, lang) {
    var d = iso ? new Date(iso) : null;
    if (!d || isNaN(d.getTime())) return '–';
    return d.toLocaleTimeString(lang === 'en' ? 'en-GB' : 'nb-NO', { hour: '2-digit', minute: '2-digit', timeZone: 'Europe/Oslo' });
  }
  function fill(tpl, vals, lang) { return tpl.replace(/\{(\w+)\}/g, function (_, k) { return fmtNum(vals[k], lang); }); }
  function textFor(data, lang) { return (data.text && (data.text[lang] || data.text[data.defaultLang])) || LONEWATCH_DATA.text.no; }
  function navigate(tab) {
    try { window.dispatchEvent(new CustomEvent('lonewatch:navigate', { detail: { tab: tab } })); } catch (e) { /* gammel nettleser: ingenting å gjøre */ }
  }

  /* ---------- Icons (24px stroke set) ---------- */
  var ICONS = {
    home: [['path', { d: 'M3 10.5 12 3l9 7.5V20a1 1 0 0 1-1 1h-5v-6H9v6H4a1 1 0 0 1-1-1z', fill: 'currentColor', stroke: 'none' }]],
    calendar: [['rect', { x: 3.5, y: 5, width: 17, height: 15.5, rx: 2.5 }], ['path', { d: 'M3.5 10h17M8 3v4M16 3v4' }]],
    bars: [['path', { d: 'M4 3v18h16' }], ['path', { d: 'M8 7h9M8 11h6M8 15h10' }]],
    chart: [['rect', { x: 3.5, y: 3.5, width: 17, height: 17, rx: 2.5 }], ['path', { d: 'M8 16v-4M12 16V8M16 16v-6' }]],
    settings: [['circle', { cx: 12, cy: 12, r: 3 }], ['path', { d: 'M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z' }]],
    bell: [['path', { d: 'M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9' }], ['path', { d: 'M10.3 21a1.9 1.9 0 0 0 3.4 0' }]],
    chevronDown: [['path', { d: 'm6 9 6 6 6-6' }]],
    chevronRight: [['path', { d: 'm9 6 6 6-6 6' }]],
    arrowRight: [['path', { d: 'M5 12h14M13 6l6 6-6 6' }]],
    arrowUpRight: [['path', { d: 'M7 17 17 7M8 7h9v9' }]],
    arrowDownLeft: [['path', { d: 'M17 7 7 17M16 17H7V8' }]],
    shield: [['path', { d: 'M12 3 4.5 6v6c0 4.5 3.2 7.8 7.5 9 4.3-1.2 7.5-4.5 7.5-9V6z' }], ['path', { d: 'm9 12 2 2 4-4' }]],
    alert: [['circle', { cx: 12, cy: 12, r: 8.5 }], ['path', { d: 'M12 7.5V13M12 16.2v.1' }]],
    check: [['circle', { cx: 12, cy: 12, r: 8.5 }], ['path', { d: 'm8.5 12 2.5 2.5 4.5-5' }]]
  };
  function Icon(props) {
    var size = props.size || 20, parts = ICONS[props.name] || [];
    return h('svg', { width: size, height: size, viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor', strokeWidth: props.strokeWidth || 1.7, strokeLinecap: 'round', strokeLinejoin: 'round', 'aria-hidden': 'true' },
      parts.map(function (p, i) { return h(p[0], Object.assign({ key: i }, p[1])); }));
  }

  /* ---------- Logo (placeholder lettermark) ---------- */
  function LogoMark(props) {
    return h('div', { className: 'lw-logo', 'aria-label': 'Lonewatch' },
      h('svg', { width: 26, height: 26, viewBox: '0 0 26 26', 'aria-hidden': 'true' },
        h('path', { d: 'M8.5 4.5 5 19.5h11.5', fill: 'none', stroke: 'currentColor', strokeWidth: 3.6, strokeLinecap: 'round', strokeLinejoin: 'round' }),
        h('circle', { cx: 19.5, cy: 8.5, r: 2.6, fill: 'currentColor' })));
  }

  /* ---------- Button ---------- */
  function Button(props) {
    var variant = props.variant || 'primary';
    var rest = Object.assign({}, props); delete rest.variant; delete rest.icon; delete rest.className;
    return h('button', Object.assign({ type: 'button' }, rest, { className: cx('lw-btn', 'lw-btn-' + variant, props.className) }),
      props.children, props.icon === false ? null : h(Icon, { name: props.icon || 'chevronRight', size: 15, strokeWidth: 2 }));
  }

  /* ---------- Language toggle ---------- */
  function LanguageToggle(props) {
    var value = props.value || LONEWATCH_DATA.defaultLang;
    var opts = [['en', 'EN', 'English'], ['no', 'NO', 'Norsk']];
    return h('div', { className: cx('lw-lang', props.vertical && 'is-vertical'), role: 'group', 'aria-label': props.label || 'Language' },
      opts.map(function (o) {
        return h('button', { key: o[0], type: 'button', className: value === o[0] ? 'is-on' : '', 'aria-pressed': value === o[0], title: o[2], onClick: function () { props.onChange && props.onChange(o[0]); } }, o[1]);
      }));
  }

  /* ---------- Sidebar ---------- */
  var NAV_ICONS = ['home', 'calendar', 'bars', 'chart', 'settings'];
  function Sidebar(props) {
    var lang = props.lang || LONEWATCH_DATA.defaultLang, t = textFor(props.data || LONEWATCH_DATA, lang);
    var TABS = ['overview', 'before', 'under', 'after', 'custom'];
    var activeState = React.useState(props.active || 0), active = activeState[0], setActive = activeState[1];
    return h('aside', { className: 'lw-sidebar' },
      h(LogoMark),
      h('nav', { className: 'lw-nav', 'aria-label': 'Main' },
        NAV_ICONS.map(function (ic, i) {
          return h('button', { key: ic, type: 'button', className: cx('lw-nav-item', i === active && 'is-active'), 'aria-label': t.nav[i], title: t.nav[i], 'aria-current': i === active ? 'page' : undefined, onClick: function () { setActive(i); props.onNavigate ? props.onNavigate(TABS[i]) : navigate(TABS[i]); } }, h(Icon, { name: ic, size: 19 }));
        })),
      h('div', { className: 'lw-sidebar-foot' },
        props.onLangChange ? h(LanguageToggle, { vertical: true, value: lang, onChange: props.onLangChange, label: t.language }) : null,
        h('button', { type: 'button', className: 'lw-nav-item', 'aria-label': t.alerts, title: t.alerts }, h(Icon, { name: 'bell', size: 19 })),
        h('div', { className: 'lw-avatar', role: 'img', 'aria-label': t.account })));
  }

  /* ---------- Glass object (approximation of the 3D render) ---------- */
  function GlassObject(props) {
    var id = useId('lwg');
    var size = props.size || 170;
    return h('svg', { width: size, height: size, viewBox: '0 0 200 200', className: props.className, 'aria-hidden': 'true' },
      h('defs', null,
        h('radialGradient', { id: id + 'b', cx: '38%', cy: '30%', r: '75%' },
          h('stop', { offset: '0%', stopColor: 'var(--blob-light)' }),
          h('stop', { offset: '22%', stopColor: 'var(--blob-mid)' }),
          h('stop', { offset: '62%', stopColor: 'var(--blob-deep)' }),
          h('stop', { offset: '100%', stopColor: '#06124a' })),
        h('linearGradient', { id: id + 's', x1: '0', y1: '0', x2: '1', y2: '1' },
          h('stop', { offset: '0%', stopColor: '#ffffff', stopOpacity: 0.95 }),
          h('stop', { offset: '60%', stopColor: 'var(--blob-light)', stopOpacity: 0.4 }),
          h('stop', { offset: '100%', stopColor: 'var(--blob-mid)', stopOpacity: 0 })),
        h('filter', { id: id + 'w', x: '-20%', y: '-20%', width: '140%', height: '140%' },
          h('feTurbulence', { type: 'fractalNoise', baseFrequency: '0.028', numOctaves: 2, seed: 11, result: 'n' }),
          h('feDisplacementMap', { in: 'SourceGraphic', in2: 'n', scale: 26, xChannelSelector: 'R', yChannelSelector: 'G' })),
        h('filter', { id: id + 'l', x: '-20%', y: '-20%', width: '140%', height: '140%' },
          h('feGaussianBlur', { in: 'SourceAlpha', stdDeviation: 4, result: 'a' }),
          h('feSpecularLighting', { in: 'a', surfaceScale: 4, specularConstant: 0.55, specularExponent: 36, lightingColor: '#d6e3ff', result: 's' },
            h('fePointLight', { x: 40, y: 10, z: 120 })),
          h('feComposite', { in: 's', in2: 'SourceAlpha', operator: 'in', result: 'sc' }),
          h('feMerge', null, h('feMergeNode', { in: 'SourceGraphic' }), h('feMergeNode', { in: 'sc' }))),
        h('filter', { id: id + 'g' }, h('feGaussianBlur', { stdDeviation: 10 }))),
      h('ellipse', { cx: 100, cy: 112, rx: 70, ry: 60, fill: 'var(--blob-mid)', opacity: 0.35, filter: 'url(#' + id + 'g)' }),
      h('g', { filter: 'url(#' + id + 'w)' },
        h('g', { filter: 'url(#' + id + 'l)' },
          h('path', { d: 'M100 30c32 0 60 20 64 50 4 32-12 62-42 74-28 11-62 6-82-16-18-22-14-58 6-82 14-16 34-26 54-26z', fill: 'url(#' + id + 'b)' }),
          FOLDS.map(function (f, i) { return h('path', { key: 'f' + i, d: f[0], fill: 'none', stroke: '#06156b', strokeWidth: f[1] * 1.3, strokeLinecap: 'round', opacity: 0.75 }); }),
          SHEEN.map(function (f, i) { return h('path', { key: 's' + i, d: f[0], fill: 'none', stroke: 'url(#' + id + 's)', strokeWidth: f[1], strokeLinecap: 'round' }); }))),
      h('ellipse', { cx: 78, cy: 60, rx: 12, ry: 5, fill: '#ffffff', opacity: 0.6, transform: 'rotate(-28 78 60)' }));
  }
  var FOLDS = [
    ['M58 64c14-16 40-22 60-12', 8], ['M140 58c10 14 14 32 6 48', 7], ['M60 96c12-8 30-6 40 4s24 10 36 0', 6],
    ['M50 124c16 14 40 18 62 10', 7], ['M120 120c10-6 20-16 24-28', 5],
    ['M104 140c14-2 28-10 36-22', 6], ['M70 46c10-6 22-8 34-6', 4]
  ];
  var SHEEN = [
    ['M66 58c14-10 34-12 50-4', 5], ['M130 64c6 10 8 22 4 32', 3.5], ['M66 88c10-6 24-4 32 4', 3.5],
    ['M58 116c14 10 32 14 50 8', 3.5], ['M112 104c8 2 16 0 22-6', 3], ['M92 132c10 0 20-4 28-10', 3], ['M120 44c8 2 14 6 18 12', 3]
  ];

  /* ---------- Promo card ---------- */
  function PromoCard(props) {
    return h('section', { className: 'lw-promo' },
      h('div', { className: 'lw-promo-art' }, props.art || h(GlassObject, { size: 170 })),
      h('h2', { className: 'lw-promo-title' }, props.title),
      h('p', { className: 'lw-promo-text' }, props.text),
      props.cta ? h(Button, { onClick: props.onCta }, props.cta) : null);
  }

  /* ---------- Panel ---------- */
  function Panel(props) {
    var head = props.title || props.action;
    return h('section', { className: cx('lw-panel', props.className), style: props.style },
      head ? h('div', { className: 'lw-panel-head' },
        h('div', null, props.title ? h('h2', { className: 'lw-panel-title' }, props.title) : null, props.subtitle ? h('p', { className: 'lw-panel-sub' }, props.subtitle) : null),
        props.action || null) : null,
      props.children);
  }
  function RangeSelect(props) { return h('button', { type: 'button', className: 'lw-select', 'aria-haspopup': 'listbox' }, props.children, h(Icon, { name: 'chevronDown', size: 15, strokeWidth: 2 })); }
  function ViewAll(props) { return h('button', { type: 'button', className: 'lw-link', onClick: props.onClick }, props.children, h('span', { className: 'lw-link-dot' }, h(Icon, { name: 'arrowRight', size: 11, strokeWidth: 2.6 }))); }

  /* ---------- Sparkline ---------- */
  function smooth(pts) {
    var d = 'M' + pts[0][0] + ' ' + pts[0][1];
    for (var i = 0; i < pts.length - 1; i++) {
      var p0 = pts[i - 1] || pts[i], p1 = pts[i], p2 = pts[i + 1], p3 = pts[i + 2] || p2;
      var c1x = p1[0] + (p2[0] - p0[0]) / 6, c1y = p1[1] + (p2[1] - p0[1]) / 6;
      var c2x = p2[0] - (p3[0] - p1[0]) / 6, c2y = p2[1] - (p3[1] - p1[1]) / 6;
      d += ' C' + c1x.toFixed(1) + ' ' + c1y.toFixed(1) + ' ' + c2x.toFixed(1) + ' ' + c2y.toFixed(1) + ' ' + p2[0].toFixed(1) + ' ' + p2[1].toFixed(1);
    }
    return d;
  }
  function toPts(data, w, top, bottom) {
    var min = Math.min.apply(null, data), max = Math.max.apply(null, data), span = max - min || 1;
    return data.map(function (v, i) { return [i * w / (data.length - 1), bottom - (v - min) / span * (bottom - top)]; });
  }
  function Sparkline(props) {
    var id = useId('lws'), W = 200, H = 88;
    var pts = toPts(props.data, W, 10, 72), d = smooth(pts);
    var ghost = props.ghost ? smooth(toPts(props.ghost, W, 18, 66)) : null;
    var marks = props.marks || [];
    return h('svg', { className: 'lw-stat-chart', viewBox: '0 0 ' + W + ' ' + H, preserveAspectRatio: 'none', 'aria-hidden': 'true' },
      h('defs', null, h('linearGradient', { id: id, x1: 0, y1: 0, x2: 0, y2: 1 },
        h('stop', { offset: '0%', stopColor: props.color, stopOpacity: 0.32 }),
        h('stop', { offset: '100%', stopColor: props.color, stopOpacity: 0 }))),
      h('path', { d: d + ' L' + W + ' ' + H + ' L0 ' + H + ' Z', fill: 'url(#' + id + ')' }),
      ghost ? h('path', { d: ghost, fill: 'none', stroke: props.color, strokeOpacity: 0.35, strokeWidth: 1.2, vectorEffect: 'non-scaling-stroke' }) : null,
      h('path', { d: d, fill: 'none', stroke: props.color, strokeWidth: 1.8, vectorEffect: 'non-scaling-stroke' }),
      marks.map(function (m) { var p = pts[m]; return h('ellipse', { key: m, cx: p[0], cy: p[1], rx: 3.4, ry: 3.4 * H / 88, fill: 'var(--card)', stroke: 'var(--ink)', strokeWidth: 1.4, vectorEffect: 'non-scaling-stroke' }); }));
  }

  /* ---------- Stat card ---------- */
  function StatCard(props) {
    var rows = props.rows || [];
    return h('article', { className: 'lw-stat' },
      h('h3', { className: 'lw-stat-title' }, props.title),
      h(Sparkline, { data: props.data, ghost: props.ghost, color: props.color || 'var(--chart-1)', marks: props.marks }),
      h('p', { className: 'lw-stat-value' }, props.value),
      rows.map(function (r, i) { return h('div', { key: i, className: 'lw-stat-row' }, h('span', null, r.label), h('i'), h('b', null, r.value)); }));
  }

  /* ---------- Progress stat ---------- */
  function ProgressStat(props) {
    var p = isNum(props.progress) ? Math.max(0, Math.min(1, props.progress)) : 0;
    return h('div', { className: 'lw-pstat' },
      h('span', { className: 'lw-pstat-icon' }, h(Icon, { name: props.icon || 'shield', size: 17 })),
      h('div', { className: 'lw-pstat-text' }, h('p', { className: 'lw-pstat-label' }, props.label), h('p', { className: 'lw-pstat-value' }, props.value)),
      h('div', { className: 'lw-bar', role: 'progressbar', 'aria-valuenow': Math.round(p * 100), 'aria-valuemin': 0, 'aria-valuemax': 100, 'aria-label': props.label },
        h('span', { style: { width: p * 100 + '%' } })));
  }

  /* ---------- Agent table ---------- */
  function AgentTable(props) {
    var lang = props.lang || LONEWATCH_DATA.defaultLang;
    return h('table', { className: 'lw-table' },
      h('thead', null, h('tr', null, props.columns.map(function (c, i) { return h('th', { key: i, scope: 'col' }, c); }))),
      h('tbody', null, props.rows.map(function (r, i) {
        return h('tr', { key: r.id || i },
          h('td', null, r.name),
          h('td', null, fmtNum(r.actions, lang)),
          h('td', null, fmtNum(r.red, lang)),
          h('td', null, fmtNum(r.blocked, lang)),
          h('td', null, fmtNum(r.allowed, lang)));
      })));
  }

  /* ---------- Status ring (samme ring som før, nå for loggkjeden) ---------- */
  function StatusRing(props) {
    var size = props.size || 124, stroke = 9, r = (size - stroke) / 2 - 2, c = size / 2;
    var sweep = 330, a0 = 150;
    var frac = props.status === 'ok' ? 1 : 0;
    function pt(a) { var rad = (a - 90) * Math.PI / 180; return [c + r * Math.cos(rad), c + r * Math.sin(rad)]; }
    function arc(x0, x1) { var p0 = pt(x0), p1 = pt(x1), large = x1 - x0 > 180 ? 1 : 0; return 'M' + p0[0].toFixed(2) + ' ' + p0[1].toFixed(2) + ' A' + r + ' ' + r + ' 0 ' + large + ' 1 ' + p1[0].toFixed(2) + ' ' + p1[1].toFixed(2); }
    var end = a0 + sweep;
    return h('div', { className: 'lw-gauge', style: { width: size, height: size }, role: 'status', 'aria-label': props.label + ': ' + props.display },
      h('svg', { width: size, height: size, viewBox: '0 0 ' + size + ' ' + size, 'aria-hidden': 'true' },
        frac < 1 ? h('path', { d: arc(a0, end), fill: 'none', stroke: 'var(--track)', strokeWidth: stroke, strokeLinecap: 'round' }) : null,
        frac > 0 ? h('path', { d: arc(a0, end), fill: 'none', stroke: 'var(--accent)', strokeWidth: stroke, strokeLinecap: 'round' }) : null),
      h('span', { className: 'lw-gauge-value' }, props.display));
  }

  /* ---------- Status rows (erstatter Audit Readiness) ---------- */
  function StatusRows(props) {
    return h('div', { className: 'lw-status-rows' }, props.rows.map(function (r, i) {
      return h('div', { key: i, className: 'lw-status-row' }, h('h2', { className: 'lw-panel-title' }, r.label), h('span', null, r.status));
    }));
  }

  /* ---------- Example tag ---------- */
  function ExampleTag(props) { return h('span', { className: 'lw-example-tag', role: 'note' }, props.children); }

  /* ---------- Dashboard (hele oversikten, tegnet fra datasettet) ---------- */
  var CHART_COLORS = ['var(--chart-1)', 'var(--chart-2)', 'var(--chart-3)'];
  function Dashboard(props) {
    var data = props.data || LONEWATCH_DATA;
    var ls = React.useState(props.lang || data.defaultLang || 'no'), lang = props.lang && props.onLangChange ? props.lang : ls[0];
    var setLang = function (l) { ls[1](l); props.onLangChange && props.onLangChange(l); };
    var go = function (tab) { props.onNavigate ? props.onNavigate(tab) : navigate(tab); };
    var t = textFor(data, lang), n = data.counts || {}, shapes = data.chartShapes || [];
    var statusText = function (st) { return st === 'ok' ? t.status.ok : st === 'broken' ? t.status.broken : t.status.none; };
    var ratio = function (a, b) { return isNum(a) && isNum(b) && b > 0 ? a / b : 0; };
    var ofText = function (a, b) { return fmtNum(a, lang) + ' ' + t.of + ' ' + fmtNum(b, lang); };
    var stats = [
      { value: n.evaluated, rows: [{ label: t.allowed, value: fmtNum(n.allowed, lang) }] },
      { value: n.red, rows: [] },
      { value: n.blocked, rows: [] }
    ];
    var lc = data.logChain || {}, sb = data.sandbox || {}, lg = data.log || {};
    var shell = h('div', { className: 'lw-shell', lang: lang === 'en' ? 'en' : 'nb' },
      h(Sidebar, { lang: lang, data: data, onLangChange: setLang, onNavigate: props.onNavigate }),
      h('main', { className: 'lw-main' },
        h('div', { className: 'lw-row-top' },
        h(PromoCard, { title: t.promoTitle, text: t.promoText, cta: t.promoCta, onCta: function () { go('custom'); } }),
        h('div', { className: 'lw-col' },
          h(Panel, { title: t.activity, action: h(RangeSelect, null, t.range) },
            h('div', { className: 'lw-stats' }, stats.map(function (st, i) {
              var sh = shapes[i] || {};
              return h(StatCard, { key: i, title: t.stats[i], value: fmtNum(st.value, lang), rows: st.rows, data: sh.data || [0, 0], ghost: sh.ghost, marks: sh.marks, color: CHART_COLORS[i] });
            }))),
          h('section', { className: 'lw-panel lw-progress-row' },
            h(ProgressStat, { icon: 'alert', label: t.waiting, value: ofText(n.waitingForHuman, n.red), progress: ratio(n.waitingForHuman, n.red) }),
            h('span', { className: 'lw-divider-v', 'aria-hidden': 'true' }),
            h(ProgressStat, { icon: 'check', label: t.followed, value: ofText(n.followedUp, n.red), progress: ratio(n.followedUp, n.red) })))),
        h('div', { className: 'lw-row-bottom' },
        h(Panel, { title: t.table, action: h(ViewAll, { onClick: function () { go('under'); } }, t.viewAll) },
          h(AgentTable, { lang: lang, columns: t.cols, rows: (data.agents || []).map(function (a) { return Object.assign({}, a, { name: (a.name && (a.name[lang] || a.name.no)) || a.id }); }) })),
        h('div', { className: 'lw-col' },
          h(Panel, null, h('div', { className: 'lw-score' },
            h('div', null, h('h2', { className: 'lw-panel-title' }, t.logChain), h('p', { className: 'lw-panel-sub' }, t.logChainSub),
              h('p', { className: 'lw-score-target' }, lc.checkedAt ? [t.lastChecked, h('b', { key: 'b' }, fmtTime(lc.checkedAt, lang))] : t.notChecked)),
            h(StatusRing, { status: lc.status, display: statusText(lc.status), label: t.logChain }))),
          h(Panel, null, h(StatusRows, { rows: [
            { label: t.sandboxRow, status: fill(t.sandboxStatus, sb, lang) },
            { label: t.logRow, status: statusText(lg.status) }
          ] }))))));
    var tag = data.isExample ? h(ExampleTag, null, t.exampleTag) : null;
    return h('div', { className: 'lw' }, props.bare
      ? h('div', { className: 'lw-bare' }, tag, shell)
      : h('div', { className: 'lw-backdrop' }, tag, shell));
  }

  window.Lonewatch = Object.assign(window.Lonewatch || {}, {
    Dashboard: Dashboard, Sidebar: Sidebar, LanguageToggle: LanguageToggle, PromoCard: PromoCard, Button: Button, Panel: Panel,
    StatCard: StatCard, ProgressStat: ProgressStat, AgentTable: AgentTable, StatusRing: StatusRing, StatusRows: StatusRows, ExampleTag: ExampleTag,
    GlassObject: GlassObject, Icon: Icon, data: LONEWATCH_DATA,
    /* Bytt datasettet (f.eks. med ekte tall fra backend). Komponenter som får `data` som prop bruker den i stedet. */
    setData: function (next) { Object.keys(LONEWATCH_DATA).forEach(function (k) { delete LONEWATCH_DATA[k]; }); Object.assign(LONEWATCH_DATA, next); }
  });
})();
