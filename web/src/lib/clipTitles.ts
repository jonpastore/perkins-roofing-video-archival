/** Clip-series title helpers. Mirror of core.miniseries.clean_title. */

const EMOJI_RE = /[\u2600-\u27BF\u{1F300}-\u{1FAFF}\uFE00-\uFE0F\u2190-\u21FF\u2B00-\u2BFF\u200D]+/gu;
const HASHTAG_RE = /(?:^|\s)#[A-Za-z]\w*/g;
const MD_ASTERISK_RE = /\*+/g;
const LEADING_JUNK_RE = /^[\s#@*•\-–—|]+/;
const TRAILING_JUNK_RE = /[\s#@*•\-–—|]+$/;

export function cleanTitle(text: string): string {
  if (!text) return "";
  let s = text.replace(EMOJI_RE, "");
  s = s.replace(HASHTAG_RE, " ");
  s = s.replace(MD_ASTERISK_RE, "");
  s = s.replace(LEADING_JUNK_RE, "").replace(TRAILING_JUNK_RE, "");
  return s.split(/\s+/).filter(Boolean).join(" ");
}

export function seriesTitle(videoTitle: string): string {
  const cleaned = cleanTitle(videoTitle);
  if (!cleaned) return "Clips";
  const MAX = 50;
  const truncated = cleaned.length > MAX
    ? cleaned.slice(0, MAX).replace(/\s+\S*$/, "").trim()
    : cleaned;
  return `${truncated} — Clips`;
}
