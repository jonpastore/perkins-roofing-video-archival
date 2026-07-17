/* Perkins coastal setback checker.
 * Distance: nearest point on the OSM coastline layer (ocean, gulf, bays, ICW).
 * Verdicts: zones.json — per-material, per-manufacturer published setback provisions.
 */
const GMAPS_KEY = "AIzaSyDU-ju5UwRWnKe7VRiUM1SiWwZ_Qf19NWI"; // referrer-restricted (this site only)
const FT_PER_M = 3.28084;

let SEGS = null;        // flat [ax,ay,bx,by] segments
let ZONES = null;
let map, marker, line;

async function loadData() {
  const [coast, zones] = await Promise.all([
    fetch("./coastline.geojson").then((r) => r.json()),
    fetch("./zones.json").then((r) => r.json()),
  ]);
  const geoms = coast.type === "GeometryCollection"
    ? coast.geometries
    : coast.features.map((f) => f.geometry);
  const segs = [];
  for (const g of geoms) {
    const c = g.coordinates;
    for (let i = 0; i + 1 < c.length; i++) segs.push(c[i][0], c[i][1], c[i + 1][0], c[i + 1][1]);
  }
  SEGS = segs;
  ZONES = zones;
}
const dataReady = loadData();

function nearestSaltwater(lat, lon) {
  const kx = 111320 * Math.cos((lat * Math.PI) / 180), ky = 110540;
  let best = Infinity, bx = 0, by = 0;
  // widen the search window until we find something (inland FL can be >60km out)
  for (let win = 0.6; win <= 6; win *= 2) {
    for (let i = 0; i < SEGS.length; i += 4) {
      const ax = SEGS[i], ay = SEGS[i + 1], cx = SEGS[i + 2], cy = SEGS[i + 3];
      if (Math.abs(ax - lon) > win || Math.abs(ay - lat) > win) continue;
      const px = (lon - ax) * kx, py = (lat - ay) * ky;
      const vx = (cx - ax) * kx, vy = (cy - ay) * ky;
      const L2 = vx * vx + vy * vy;
      const t = L2 ? Math.max(0, Math.min(1, (px * vx + py * vy) / L2)) : 0;
      const dx = px - t * vx, dy = py - t * vy;
      const d = dx * dx + dy * dy;
      if (d < best) {
        best = d;
        bx = ax + (t * vx) / kx; by = ay + (t * vy) / ky;
      }
    }
    if (best < Infinity) break;
  }
  return { meters: Math.sqrt(best), nearest: [by, bx] };
}

function loadGmaps() {
  return new Promise((resolve, reject) => {
    if (window.google?.maps?.Geocoder) return resolve();
    const s = document.createElement("script");
    s.src = `https://maps.googleapis.com/maps/api/js?key=${GMAPS_KEY}&loading=async&callback=__gm`;
    window.__gm = () => resolve();
    s.onerror = reject;
    document.head.appendChild(s);
  });
}

function geocode(addr) {
  return new Promise((resolve, reject) => {
    new google.maps.Geocoder().geocode(
      {
        address: addr,
        componentRestrictions: { country: "US" },
        bounds: new google.maps.LatLngBounds({ lat: 24.3, lng: -87.7 }, { lat: 31.2, lng: -79.7 }),
      },
      (res, status) => {
        if (status === "OK" && res?.length) resolve(res[0]);
        else reject(new Error(status === "ZERO_RESULTS" ? "Address not found — try adding city and ZIP." : `Geocoding failed (${status}).`));
      }
    );
  });
}

function fmtDist(m) {
  const ft = m * FT_PER_M;
  return ft < 5280 ? `${Math.round(ft).toLocaleString()} ft` : `${(ft / 5280).toFixed(1)} mi`;
}

function verdictFor(material, meters) {
  // returns {cls, label, details[]} from per-manufacturer provisions
  const ft = meters * FT_PER_M;
  const rows = [];
  let anyVoid = false, anyCond = false;
  for (const p of material.provisions) {
    let state = "ok";
    if (p.void_within_ft != null && ft < p.void_within_ft) state = "void";
    else if (p.conditional_within_ft != null && ft < p.conditional_within_ft) state = "cond";
    if (state === "void") anyVoid = true;
    if (state === "cond") anyCond = true;
    rows.push({ mfr: p.manufacturer, state, note: p.note });
  }
  const cls = anyVoid ? "void" : anyCond ? "cond" : "ok";
  const label = anyVoid ? "Warranty VOID for some brands" : anyCond ? "Conditional — check brand terms" : "Warranty-safe";
  return { cls, label, rows };
}

async function check() {
  const addr = document.getElementById("addr").value.trim();
  const status = document.getElementById("status");
  const result = document.getElementById("result");
  if (!addr) { status.innerHTML = '<p class="err">Enter an address first.</p>'; return; }
  document.getElementById("go").disabled = true;
  status.innerHTML = '<p class="spin">Locating and measuring…</p>';
  result.innerHTML = "";
  try {
    await dataReady;
    await loadGmaps();
    const g = await geocode(addr);
    const lat = g.geometry.location.lat(), lon = g.geometry.location.lng();
    const { meters, nearest } = nearestSaltwater(lat, lon);

    if (!map) {
      map = L.map("map");
      L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png",
        { attribution: "© OpenStreetMap" }).addTo(map);
    }
    if (marker) map.removeLayer(marker);
    if (line) map.removeLayer(line);
    marker = L.marker([lat, lon]).addTo(map).bindPopup(g.formatted_address);
    line = L.polyline([[lat, lon], nearest], { color: "#ef3c1a", dashArray: "6 6" }).addTo(map);
    map.fitBounds(L.latLngBounds([[lat, lon], nearest]).pad(0.5));

    const cards = ZONES.materials.map((m) => {
      const v = verdictFor(m, meters);
      const rows = v.rows.map((r) =>
        `<tr><td>${r.mfr}</td><td class="${r.state}">${
          r.state === "ok" ? "Covered" : r.state === "cond" ? "Conditional" : "Void"
        }</td><td class="note">${r.note || ""}</td></tr>`).join("");
      return `<div class="verdict"><h2>${m.name} — <span class="${v.cls}">${v.label}</span></h2>
        <p class="note" style="margin-bottom:8px">${m.blurb || ""}</p>
        <table><tr><th>Manufacturer</th><th>At your distance</th><th>Provision</th></tr>${rows}</table></div>`;
    }).join("");

    result.innerHTML = `
      <div class="verdict">
        <h2>${g.formatted_address}</h2>
        <p class="dist">Distance to mapped salt water: <strong>${fmtDist(meters)}</strong></p>
        ${ZONES.banner ? `<div class="advisory">${ZONES.banner}</div>` : ""}
        <div class="advisory">On a canal or waterway that connects to the ocean or Intracoastal?
        Manufacturers treat tidal canals as salt water — if your home is canal-front, use the
        waterfront (most protective) recommendation regardless of the distance shown.</div>
      </div>
      ${cards}
      <a class="cta" href="https://perkinsroofing.net/contact/" target="_blank" rel="noopener">
        Get a free quote with the right material for your home →</a>`;
    status.innerHTML = "";
  } catch (e) {
    status.innerHTML = `<p class="err">${e.message || e}</p>`;
  } finally {
    document.getElementById("go").disabled = false;
  }
}
window.check = check;
