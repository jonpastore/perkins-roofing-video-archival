import { BRAND } from "../ui";

// Feature help for Clip Studio — one entry per video/audio/publishing feature we built.
const HELP: { group: string; items: { title: string; body: string }[] }[] = [
  {
    group: "Video",
    items: [
      { title: "Reframe (9:16)", body: "Crops landscape footage to a vertical format ready for Reels, TikTok, and YouTube Shorts. Use it to repurpose standard recordings for mobile-first feeds." },
      { title: "Speaker tracking", body: "Keeps the person speaking centered in frame as they move while reframing. Ideal for shots where the subject walks around or shifts position." },
      { title: "Focal point", body: "A manual slider to choose what stays in frame when speaker tracking is off. Best for highlighting a static detail — a roof feature or piece of equipment." },
      { title: "Scene detection", body: "Finds natural cut points — pauses in speech, or visual camera cuts — so you can trim a clip to a clean scene without scrubbing. 'Visual' analyzes the video; the default uses the transcript." },
      { title: "Captions", body: "Burns styled on-screen captions from the transcript (Bold Yellow, TikTok Pop, Reels Clean, Shorts Editorial — or Off). Boosts retention for sound-off viewing." },
      { title: "Emoji highlights", body: "Adds relevant emoji on keywords in the captions for extra visual pop." },
      { title: "Aspect exports", body: "Also exports square (1:1) and wide (16:9) versions alongside the vertical clip, so one edit covers multiple placements." },
    ],
  },
  {
    group: "Audio",
    items: [
      { title: "Auto-censor", body: "Automatically mutes flagged/profane words in the audio AND masks them in the burned captions. Uses the crude denylist plus your Marketing safety denylist. Runs on every render." },
      { title: "Speech cleanup", body: "Removes filler words ('um', 'uh') and long pauses for a tighter, more professional edit." },
      { title: "Audio enhance", body: "Denoise + compress + normalize loudness to broadcast level (EBU R128, −14 LUFS) — voice stays clear even from a noisy job site." },
      { title: "Background music", body: "Adds a royalty-free music bed under the dialogue to fill silence and set the mood." },
    ],
  },
  {
    group: "Publishing",
    items: [
      { title: "Platform presets", body: "Tunes the AI clip suggestions — hook length, caption style, hashtag count — for a target platform (Instagram, TikTok, YouTube Shorts, Facebook)." },
      { title: "Platform fit check", body: "Shows a green ✓ or amber ⚠ per platform on each clip, based on its length vs the platform's spec — so you catch a too-long clip before scheduling." },
      { title: "Publish targets", body: "Choose which platforms (Instagram, TikTok today) the finished clip posts to. Only connected platforms are selectable." },
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
          <div style={{ fontWeight: 800, color: BRAND.navyText, fontSize: 17 }}>Clip Studio — video &amp; audio features</div>
          <button onClick={onClose} style={{ background: "none", border: "none", cursor: "pointer", fontSize: 24, color: BRAND.sub, lineHeight: 1 }}>×</button>
        </div>
        <div style={{ padding: "8px 22px 22px" }}>
          {HELP.map((g) => (
            <div key={g.group} style={{ marginTop: 16 }}>
              <div style={{ fontSize: 12, fontWeight: 700, color: BRAND.red, textTransform: "uppercase", letterSpacing: 0.5, marginBottom: 8 }}>{g.group}</div>
              {g.items.map((it) => (
                <div key={it.title} style={{ marginBottom: 12 }}>
                  <div style={{ fontWeight: 700, color: BRAND.navyText, fontSize: 13.5 }}>{it.title}</div>
                  <div style={{ fontSize: 13, color: BRAND.ink, lineHeight: 1.5, marginTop: 2 }}>{it.body}</div>
                </div>
              ))}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
