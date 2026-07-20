import { BRAND } from "../ui";

// Feature help for Clip Studio. Grouped by WHERE each control lives in the UI —
// validated 1:1 against ClipStudio.tsx so the help matches what's actually on screen.
// `where` tells you the exact spot; `req` notes anything that must be toggled first.
const HELP: {
  group: string;
  blurb?: string;
  items: { title: string; body: string; req?: string }[];
}[] = [
  {
    group: "Step 2 — AI clip suggestions",
    blurb: "Shown after you pick a source video, before you generate suggestions.",
    items: [
      { title: "Platform presets", body: "The platform buttons (General / Instagram / TikTok / YouTube Shorts / Facebook) above “Suggest clips”. They tune the AI suggestions — hook length, caption style, hashtag count — for that platform. Optional; defaults to General." },
    ],
  },
  {
    group: "On each suggested clip card",
    blurb: "Appears on every clip after suggestions come back (Step 2, “Review suggested clips”).",
    items: [
      { title: "Scene detection", body: "The “✂ Detect scenes” button (and the “visual” button next to it) on each clip. Finds natural cut points — the default uses the transcript (speech gaps); “visual” analyses the video for camera cuts (slower). Click a returned “cut @ …s” chip to trim the clip to that point." },
      { title: "Platform fit check", body: "The “Fits” row of green ✓ / amber ⚠ chips per platform on each clip, based on its length vs each platform’s spec — so you catch a too-long clip before saving." },
    ],
  },
  {
    group: "Render options — in the “Ready to Render” panel",
    blurb: "IMPORTANT: these controls are hidden until you (1) Suggest clips, (2) “Save as clip series”, then (3) scroll to the “Ready to Render” panel and click “Render options ▼” on that series. They do not appear while you are still choosing clips.",
    items: [
      { title: "Reframe (9:16)", body: "Crops landscape footage to vertical for Reels / TikTok / Shorts." },
      { title: "Speaker tracking", body: "Tries to keep the speaker centered as they move while reframing. Falls back to a centre crop when the face-detector adapter isn’t wired on the server.", req: "Turn Reframe ON first — this control is hidden otherwise." },
      { title: "Focal point", body: "A manual slider to choose what stays in frame — good for a static detail (a roof feature, a piece of equipment).", req: "Shown only when Reframe is ON and Speaker tracking is OFF." },
      { title: "Captions", body: "Burns styled on-screen captions from the transcript. Styles: Bold Yellow, TikTok Pop, Reels Clean, Shorts Editorial — or “Off” for no burned captions. Choose Bottom or Top position." },
      { title: "Emoji highlights", body: "Appends roofing-domain emoji to matched keywords in the captions." },
      { title: "Speech cleanup", body: "Removes filler words (“um”, “uh”) and long pauses for a tighter edit. Requires a transcript." },
      { title: "Audio enhance", body: "Denoise + compress + normalize loudness to broadcast level (EBU R128, −14 LUFS)." },
      { title: "Background music", body: "Adds a royalty-free music bed (Pixabay / FMA) under the dialogue. Requires a track ID." },
      { title: "Export aspects", body: "9:16 always renders; optionally also export 1:1 square (1080×1080) and 16:9 wide (1920×1080) from the same edit." },
      { title: "Publish targets", body: "The “Publish to” checkboxes — which connected platforms the finished clip auto-schedules to (Instagram / TikTok today). None checked = Instagram + TikTok." },
    ],
  },
  {
    group: "Automatic — no control to set",
    items: [
      { title: "Auto-censor", body: "Runs on every render with no toggle: mutes flagged/profane words in the audio AND masks them in the burned captions. Uses the crude denylist plus your Marketing → safety denylist. There is nothing to turn on — it is always active." },
    ],
  },
];

export function ClipStudioHelp({ onClose }: { onClose: () => void }) {
  return (
    <div
      onClick={onClose}
      style={{ position: "fixed", inset: 0, zIndex: 1000, background: "rgba(16,24,40,0.45)", display: "flex", alignItems: "flex-start", justifyContent: "center", padding: "40px 16px", overflowY: "auto" }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{ width: "min(680px, 96vw)", background: "#fff", borderRadius: 12, boxShadow: "0 20px 50px rgba(16,24,40,0.25)" }}
      >
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "16px 22px", borderBottom: `1px solid ${BRAND.border}` }}>
          <div style={{ fontWeight: 800, color: BRAND.navyText, fontSize: 17 }}>Clip Studio — features &amp; where to find them</div>
          <button onClick={onClose} style={{ background: "none", border: "none", cursor: "pointer", fontSize: 24, color: BRAND.sub, lineHeight: 1 }}>×</button>
        </div>
        <div style={{ padding: "8px 22px 22px" }}>
          <div style={{ marginTop: 12, padding: "10px 12px", background: BRAND.bg, borderRadius: 8, fontSize: 12.5, color: BRAND.ink, lineHeight: 1.5 }}>
            <strong>The flow:</strong> pick a source video → <strong>Suggest clips</strong> → curate &amp; <strong>Save as clip series</strong> → in <strong>Ready to Render</strong>, open <strong>Render options ▼</strong> on that series to set reframe, captions, audio, and publishing → <strong>Render now</strong>. Most controls below live in that Render options panel and won’t appear until a series is saved.
          </div>
          {HELP.map((g) => (
            <div key={g.group} style={{ marginTop: 18 }}>
              <div style={{ fontSize: 12, fontWeight: 700, color: BRAND.red, textTransform: "uppercase", letterSpacing: 0.5, marginBottom: 4 }}>{g.group}</div>
              {g.blurb && (
                <div style={{ fontSize: 12, color: BRAND.sub, lineHeight: 1.45, marginBottom: 8 }}>{g.blurb}</div>
              )}
              {g.items.map((it) => (
                <div key={it.title} style={{ marginBottom: 12 }}>
                  <div style={{ fontWeight: 700, color: BRAND.navyText, fontSize: 13.5 }}>{it.title}</div>
                  <div style={{ fontSize: 13, color: BRAND.ink, lineHeight: 1.5, marginTop: 2 }}>{it.body}</div>
                  {it.req && (
                    <div style={{ fontSize: 12, color: "#9a6400", background: "#fdf0e3", borderRadius: 6, padding: "3px 8px", marginTop: 4, display: "inline-block" }}>
                      ⚠ {it.req}
                    </div>
                  )}
                </div>
              ))}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
