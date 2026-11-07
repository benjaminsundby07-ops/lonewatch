/* Hvordan et skrevet beløp tolkes, i nettleseren.
 *
 * Dette er den samme regelen som ui/amount.py. Endrer du én av dem, må du endre
 * begge: tests/test_amount.py kjører nøyaktig samme tilfeller gjennom begge og
 * feiler hvis de er uenige. Grunnen er at knappen her lyser grønt for det
 * tjeneren kommer til å godta - blir de uenige, betyr "skriv beløpet" to
 * forskjellige ting to steder. Se F1 i docs/REDTEAM.md.
 */
(function (root) {
  "use strict";

  var MAX_INPUT_CHARS = 64;
  /* 13 siffer: et JS-tall er eksakt opp til 2^53, og dette holder oss under.
   * Samme grense i ui/amount.py, ellers blir de to uenige om store beloep. */
  var MAX_DIGITS = 13;
  var SPACES = " \t\u00a0\u202f";
  var CURRENCY_SUFFIX = /(?:kr|nok|kroner)$/i;
  var GROUP_SEPARATORS = /[ \t\u00a0\u202f.]/;
  var ONLY_DIGITS = /^[0-9]+$/;

  function trimSpaces(s) {
    return s.replace(/^[ \t\u00a0\u202f\r\n]+|[ \t\u00a0\u202f\r\n]+$/g, "");
  }

  /* Tolker et skrevet beløp og gir hele øre, eller null. */
  function parseAmountOre(text) {
    if (typeof text !== "string") return null;

    var cleaned = trimSpaces(text);
    if (!cleaned || cleaned.length > MAX_INPUT_CHARS) return null;

    cleaned = trimSpaces(cleaned.replace(CURRENCY_SUFFIX, ""));
    if (!cleaned) return null;

    var whole;
    var orePart = 0;
    var commas = cleaned.split(",").length - 1;
    if (commas > 1) return null;
    if (commas === 1) {
      var delt = cleaned.split(",");
      whole = delt[0];
      var fraction = delt[1];
      if (!ONLY_DIGITS.test(fraction) || fraction.length > 2) return null;
      orePart = parseInt(fraction.length === 1 ? fraction + "0" : fraction, 10);
    } else {
      whole = cleaned;
    }

    var groups = whole.split(GROUP_SEPARATORS);
    for (var i = 0; i < groups.length; i++) {
      if (!ONLY_DIGITS.test(groups[i])) return null;
    }
    if (groups.length > 1) {
      if (groups[0].length < 1 || groups[0].length > 3) return null;
      for (var j = 1; j < groups.length; j++) {
        if (groups[j].length !== 3) return null;
      }
    }

    var digits = groups.join("");
    if (digits.length > MAX_DIGITS) return null;

    /* Number klarer heltall opp til 2^53. MAX_DIGITS over holder oss under. */
    return Number(digits) * 100 + orePart;
  }

  /* Beløpet fra forespørselen som hele øre, eller null. */
  function toOre(amount) {
    if (amount === null || amount === undefined) return null;
    if (typeof amount !== "number" || !isFinite(amount)) return null;
    return Math.round(amount * 100);
  }

  /* Skrev mennesket nøyaktig det beløpet forespørselen gjelder? */
  function amountMatches(typed, expected) {
    var forventet = toOre(expected);
    if (forventet === null) return false;
    var skrevet = parseAmountOre(typed);
    if (skrevet === null) return false;
    return skrevet === forventet;
  }

  root.LonewatchAmount = {
    parseAmountOre: parseAmountOre,
    toOre: toOre,
    amountMatches: amountMatches,
    SPACES: SPACES,
  };
})(typeof globalThis !== "undefined" ? globalThis : this);
