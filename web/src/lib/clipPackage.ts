export const CLIP_MIN_SECS = 15;
export const CLIP_MAX_SECS = 40;

export function clipLengthSecs(start: number, end: number): number {
  return Number(end || 0) - Number(start || 0);
}

export function missingPackageFields(clip: {
  town?: string;
  problem?: string;
  hook?: string;
  audience?: string;
  phone_cta?: string;
  start: number;
  end: number;
}): string[] {
  const missing: string[] = [];
  if (!String(clip.town || "").trim()) missing.push("town");
  if (!String(clip.problem || "").trim()) missing.push("problem");
  if (!String(clip.hook || "").trim()) missing.push("hook");
  const audience = String(clip.audience || "").trim().toLowerCase();
  if (audience !== "homeowner" && audience !== "roofer") missing.push("audience");
  if (!String(clip.phone_cta || "").trim()) missing.push("phone_cta");
  const length = clipLengthSecs(clip.start, clip.end);
  if (length < CLIP_MIN_SECS || length > CLIP_MAX_SECS) missing.push("length");
  return missing;
}
