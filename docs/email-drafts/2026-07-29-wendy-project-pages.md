# 2026-07-29 — Wendy (cc Tim): where project pages live, and what they need

To: wendy@webpowermarketing.com
Cc: tim@perkinsroofing.net
Subject: Project pages — where should they live, and what are the requirements?

**Supersedes the 2026-07-29 01:59 draft**, which asked whether we should embed "the relevant
YouTube video" on each project page and said matching a project to its video was
straightforward. It isn't, and the media should come from CompanyCam instead — see
"Why the video ask was dropped" below.

---

Hi Wendy,

We're getting ready to automate project write-ups the same way we do articles, and before we
build the pipeline I want to make sure we're publishing them where you actually want them, in
the shape you want.

**1) Where should project pages live?**

There are currently two places projects exist on the site, and they disagree:

- Nine published projects are WordPress **pages**, children of `/portfolio/` — e.g.
  `/portfolio/sunny-isles-condominium-ac-towers-re-roof-in-sunny-isles-beach-fl/`. These are
  the ones the public sees. All nine are dated May 2023.
- The Avada theme also registers a separate **Portfolio post type**, publishing to
  `/portfolio-items/`. It has no published entries today, though it was clearly used at some
  point — the old category names (Commercial Projects, Renovations) are still there.

Should new projects be pages under `/portfolio/` to match the nine you have, or should we move
to the Avada Portfolio type? If it's the latter, `/portfolio-items/` is live and empty today,
which isn't ideal for search either way.

**2) Do you have a schema and requirements for project write-ups?**

Your article criteria were genuinely useful — we turned them into an automated checklist every
article has to pass before it can publish, and it loops until it's compliant or blocks. We'd
like to do the same for projects, but we don't want to invent the standard.

- Is there structured data (JSON-LD) you want on project pages? The nine live ones have none;
  the articles carry FAQPage and VideoObject.
- Any required sections, length, or format for the write-up?
- Rules for images — how many, and what alt text? Each project currently has exactly four
  images and all four share one alt string, which reads as templated.
- Should projects link out to the relevant service and location pages? None of the nine do,
  even where the page exists — Sunny Isles has a
  `/south-florida-service-areas/miami-dade/sunny-isles-beach/` page its project doesn't link to.

**On photos and video:** the crews document every job in CompanyCam, so we can build project
galleries from real media rather than asking anyone to re-upload. Checking a sample of 25
projects: **2,554 photos, and 234 videos across 20 of the 25** — so most projects have real
on-site video too, tied to the actual job. If you want video on project pages, that's the
source, and it will be footage of that specific property.

On YouTube specifically: where your project doc already names a video for a project we'll use
that one — five of the fourteen do. What we won't do is try to work the match out ourselves. The
channel is educational and marketing content organised by topic, not per-project documentation,
so there's nothing reliable to match on: the only video mentioning Sunny Isles is "Major
Waterproofing Fail in Sunny Isles," which is emphatically not the AC Towers project and would be
a bad thing to put on it. If you want video on the other projects, CompanyCam is the source.

If you'd rather talk it through than write it up, happy to do a call.

One related thing for Tim: before any of this goes public we need to know which projects have
client permission to name the property and use the photos and video.

Thanks,
Jon

---

## Working notes (not part of the email)

### Why the video ask was dropped

Checked, rather than assumed:

- 856 videos in the catalog. Titles that name a **property**: effectively none. Titles are
  topic-shaped ("How to Install Tile on a Tower Roof in Florida — Part 7", "Quick roofing tip
  from Palm Beach County"); 122 open with an explicit how-to/why/what pattern.
- `condominium`: 0 titles. `association`: 0. `AC Tower`: 0. `sunny isles`: 1 — and it is
  *"🚨 Major Waterproofing Fail in Sunny Isles."*, a failure short, not the AC Towers re-roof.
- So there is no key to join videos to projects, and the nearest-title match on the one project
  we could test would have embedded a failure video on a showcase page.

CompanyCam is the opposite: projects are keyed by customer name (Butterworth, Malooley, Suntide
Condo …) which lines up with the sold record and the golden proposals, and the media is of the
actual property.

### Current state of the plumbing (2026-07-29)

| | status |
|---|---|
| CompanyCam application key | live, verified (`/v2/projects`, photos, videos all 200) |
| `jobs/companycam_sync.py` | exists, pulls **photos only**, and is **not deployed or scheduled** |
| `companycam_photos` table | exists, **0 rows** — nothing has ever synced |
| `adapters.companycam.list_videos` | exists (added 2026-07-28), **called by nothing** |
| SPA `Portfolio.tsx` | lists candidates, shows gate/permission badges, one-click publish |
| `avada_portfolio` CPT | 13 drafts, all ours, `featured_media: 0`, no categories |

So the honest answer to "are we pulling CompanyCam media?" is **no — not yet**. The key works
and the adapter can read both photos and video; nothing runs it.

⚠️ CompanyCam media carries an `internal` flag. Internal media must never reach a proposal or a
public project page — `normalize_video` carries the flag through for exactly this reason, and
any publisher has to filter on it.
