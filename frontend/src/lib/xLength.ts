/**
 * A text's length the way X counts it: the same hand port of twitter-text 3.1.0's v3
 * weighting as backend/app/publishing/x_length.py, which is authoritative. Both are tested
 * against the backend's shared cases.
 *
 * After NFC normalization, a URL counts 23, an emoji sequence 2, a code point in the light
 * ranges 1, and any other code point 2. URL matching follows twitter-text's extractUrl regex
 * and TLD list (Copyright 2018 Twitter, Inc., Apache License 2.0).
 */
import { X_TLDS } from './xTlds';

const URL_LENGTH = 23;
const SCALE = 100;
const DEFAULT_WEIGHT = 200;
const LIGHT_RANGES: readonly [number, number][] = [
  [0, 4351],
  [8192, 8205],
  [8208, 8223],
  [8242, 8247],
];
const MAX_URL_LENGTH = 4096;
const MAX_TCO_SLUG_LENGTH = 40;

interface Trie {
  [char: string]: Trie;
}

/** An alternation of `words` as a prefix trie, matching the backend's regex. */
function triePattern(words: readonly string[]): string {
  const trie: Trie = {};
  for (const word of words) {
    let node = trie;
    for (const char of word) node = node[char] ??= {};
    node[''] = {};
  }
  const pattern = (node: Trie): string => {
    const branches = Object.entries(node)
      .filter(([char]) => char)
      .map(([char, child]) => char + pattern(child));
    if (!branches.length) return '';
    const body = branches.length === 1 ? branches[0] : `(?:${branches.join('|')})`;
    return '' in node ? `(?:${body})?` : body;
  };
  return `(?:${pattern(trie)})`;
}

const TLD = `${triePattern(X_TLDS)}(?=[^0-9a-zA-Z@+\\-]|$)`;
const PUNYCODE = '(?:xn--[\\-0-9a-z]+)';
const LATIN_ACCENTS =
  '\\u00c0-\\u00d6\\u00d8-\\u00f6\\u00f8-\\u00ff\\u0100-\\u024f\\u0253\\u0254\\u0256\\u0257' +
  '\\u0259\\u025b\\u0263\\u0268\\u026f\\u0272\\u0289\\u028b\\u02bb\\u0300-\\u036f\\u1e00-\\u1eff';
const DIRECTIONAL = '\\u202a-\\u202e\\u061c\\u200e\\u200f\\u2066-\\u2069';
const INVALID = '\\ufffe\\ufeff\\uffff';
const SPACES =
  '\\u0009-\\u000d\\u0020\\u0085\\u00a0\\u1680\\u180e\\u2000-\\u200a\\u2028\\u2029\\u202f\\u205f\\u3000';
const PUNCT = "!'#%&()*+,\\\\\\-./:;<=>?@\\[\\]\\^_{|}~$";
const DOMAIN_CHAR = `[^${PUNCT}${SPACES}${INVALID}${DIRECTIONAL}]`;
const SUBDOMAIN = `(?:(?:${DOMAIN_CHAR}(?:[_\\-]|${DOMAIN_CHAR})*)?${DOMAIN_CHAR}\\.)`;
const DOMAIN_NAME = `(?:(?:${DOMAIN_CHAR}(?:-|${DOMAIN_CHAR})*)?${DOMAIN_CHAR}\\.)`;
// At most 127 labels, as on the backend: unbounded, a text like "a.a.a." stalls the regex.
const DOMAIN = `(?:${SUBDOMAIN}{0,126}${DOMAIN_NAME}(?:${TLD}|${PUNYCODE}))`;
const PATH_CHAR = `[a-z\\u0400-\\u04ff0-9!*';:=+,.$/%#\\[\\]\\-\\u2013_~@|&${LATIN_ACCENTS}]`;
const BALANCED_PARENS = `\\((?:${PATH_CHAR}+|(?:${PATH_CHAR}*\\(${PATH_CHAR}+\\)${PATH_CHAR}*))\\)`;
const PATH_END = `(?:[+\\-a-z\\u0400-\\u04ff0-9=_#/${LATIN_ACCENTS}]|(?:${BALANCED_PARENS}))`;
const PATH = `(?:(?:${PATH_CHAR}*(?:${BALANCED_PARENS}${PATH_CHAR}*)*${PATH_END})|(?:@${PATH_CHAR}+/))`;
const QUERY_CHAR = "[a-z0-9!?*'@();:&=+$/%#\\[\\]\\-_.,~|]";
const QUERY_END = '[a-z0-9\\-_&=#/]';
const PRECEDING = `(?:[^A-Za-z0-9@\\uff20$#\\uff03${INVALID}]|[${DIRECTIONAL}]|^)`;

const URL_PATTERN = new RegExp(
  `(?<before>${PRECEDING})` +
    `(?<url>(?<protocol>https?://)?(?<domain>${DOMAIN})(?::[0-9]+)?` +
    `(?<path>/${PATH}*)?(?:\\?${QUERY_CHAR}*${QUERY_END})?)`,
  'giu',
);
const ASCII_DOMAIN = new RegExp(
  `(?:(?:[\\-a-z0-9${LATIN_ACCENTS}]+)\\.)+(?:${TLD}|${PUNYCODE})`,
  'giu',
);
const INVALID_BEFORE_BARE_DOMAIN = /[-_./]$/u;
const TCO_URL = new RegExp(`^https?://t\\.co/([a-z0-9]+)(?:\\?${QUERY_CHAR}*${QUERY_END})?`, 'u');

const EMOJI_BASE =
  '[\\u00a9\\u00ae\\u203c\\u2049\\u2122\\u2139\\u2194-\\u21ff\\u2300-\\u23ff\\u24c2\\u25a0-\\u27bf' +
  '\\u2900-\\u297f\\u2b00-\\u2bff\\u3030\\u303d\\u3297\\u3299\\u{1f000}-\\u{1faff}]';
const EMOJI_MODIFIER = '[\\ufe0f\\u{1f3fb}-\\u{1f3ff}]';
// eslint-disable-next-line no-misleading-character-class -- modifiers are matched one code point at a time on purpose.
const EMOJI = new RegExp(
  '[\\u{1f1e6}-\\u{1f1ff}]{2}' +
    '|[0-9#*]\\ufe0f?\\u20e3' +
    '|\\u{1f3f4}[\\u{e0020}-\\u{e007e}]+\\u{e007f}' +
    `|${EMOJI_BASE}${EMOJI_MODIFIER}*(?:\\u200d${EMOJI_BASE}${EMOJI_MODIFIER}*)*`,
  'gu',
);

/** The length X gives `text` when it checks the post limit. */
export function xWeightedLength(text: string): number {
  const normalized = text.normalize('NFC');
  const urlEnds = urlSpans(normalized);
  // A single code point weighs the same as an emoji or not, so only sequences need a span.
  const emojiEnds = new Map<number, number>();
  for (const m of normalized.matchAll(EMOJI)) {
    if ([...m[0]].length > 1) emojiEnds.set(m.index, m.index + m[0].length);
  }

  let units = 0;
  let index = 0;
  while (index < normalized.length) {
    const urlEnd = urlEnds.get(index);
    const emojiEnd = emojiEnds.get(index);
    if (urlEnd !== undefined) {
      units += URL_LENGTH * SCALE;
      index = urlEnd;
    } else if (emojiEnd !== undefined) {
      units += DEFAULT_WEIGHT;
      index = emojiEnd;
    } else {
      const codePoint = normalized.codePointAt(index) ?? 0;
      units += weight(codePoint);
      index += codePoint > 0xffff ? 2 : 1;
    }
  }
  return Math.floor(units / SCALE);
}

function weight(codePoint: number): number {
  return LIGHT_RANGES.some(([start, end]) => start <= codePoint && codePoint <= end)
    ? SCALE
    : DEFAULT_WEIGHT;
}

/** Each URL X would shorten, as start index to end index (UTF-16). */
function urlSpans(text: string): Map<number, number> {
  const spans = new Map<number, number>();
  if (!text.includes('.')) return spans;
  for (const m of text.matchAll(URL_PATTERN)) {
    const { before = '', url = '', protocol, domain = '', path } = m.groups ?? {};
    const start = m.index + before.length;
    let end = start + url.length;
    if ((protocol ?? 'https://').length + [...url].length > MAX_URL_LENGTH) continue;
    if (protocol) {
      const tco = TCO_URL.exec(url);
      if (tco) {
        if ([...tco[1]].length > MAX_TCO_SLUG_LENGTH) continue;
        end = start + tco[0].length;
      }
      spans.set(start, end);
      continue;
    }
    // Without a protocol, only ASCII domains count, and not right after "-", "_", "." or "/".
    if (INVALID_BEFORE_BARE_DOMAIN.test(before)) continue;
    let lastStart: number | null = null;
    for (const ascii of domain.matchAll(ASCII_DOMAIN)) {
      lastStart = start + ascii.index;
      spans.set(lastStart, lastStart + ascii[0].length);
    }
    if (lastStart !== null && path) spans.set(lastStart, end);
  }
  return spans;
}
