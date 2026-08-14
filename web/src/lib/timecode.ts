/** hh:mm:ss helpers used by Video Approval's editable part times. */

export function fmtHMS(secs: number): string {
  const s = Math.max(0, Math.floor(secs || 0));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  const p = (n: number) => String(n).padStart(2, "0");
  return `${p(h)}:${p(m)}:${p(sec)}`;
}

/** Lenient "hh:mm:ss" / "mm:ss" / "ss" -> seconds. null if any part is non-numeric. */
export function parseHMS(str: string): number | null {
  const parts = str.split(":").map((p) => p.trim());
  if (parts.some((p) => p !== "" && Number.isNaN(Number(p)))) return null;
  return parts.reduce((acc, p) => acc * 60 + Number(p || 0), 0);
}
