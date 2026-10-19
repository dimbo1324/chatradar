// UI text lives in static/i18n/ru.json (data), never in the code. Keys are plain strings;
// a value is a string or, for counted nouns, an object with the Russian plural forms
// one / few / many (and other). Values only ever become text nodes.

const LOCALE = "ru";
const messages = {};
const plural = new Intl.PluralRules(LOCALE);
const numbers = new Intl.NumberFormat(LOCALE);
const percents = new Intl.NumberFormat(LOCALE, { style: "percent", maximumFractionDigits: 1 });
const decimals = new Intl.NumberFormat(LOCALE, { minimumFractionDigits: 1, maximumFractionDigits: 1 });

export async function loadLocale(signal = undefined) {
  const response = await fetch(`/static/i18n/${LOCALE}.json`, { signal });
  if (!response.ok) throw new Error(`Locale ${LOCALE} not loaded (HTTP ${response.status})`);
  Object.assign(messages, await response.json());
  document.documentElement.lang = LOCALE;
}

export function num(value) {
  return numbers.format(value);
}

export function pct(value) {
  return percents.format(value);
}

export function dec(value) {
  return decimals.format(value);
}

function fill(template, vars) {
  return template.replace(/\{(\w+)\}/g, (whole, name) => (name in vars ? String(vars[name]) : whole));
}

export function t(key, vars = {}) {
  const value = messages[key];
  return typeof value === "string" ? fill(value, vars) : key;
}

// Plural lookup: picks the Russian plural form (one/few/many) for n; {n} is the formatted number.
export function tn(key, n, vars = {}) {
  const forms = messages[key];
  if (!forms || typeof forms !== "object") return key;
  const form = forms[plural.select(n)] ?? forms.other ?? forms.many;
  return fill(form, { n: num(n), ...vars });
}

// Server-side values (noise reasons, stages, media types…) are translated when known and
// shown as they are otherwise, so a new backend value never breaks a page.
export function tEnum(prefix, value) {
  const found = messages[`${prefix}.${value}`];
  return typeof found === "string" ? found : String(value);
}
