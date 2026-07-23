/* Perkins coastal metal-roof warranty checker (WordPress plugin build).
 * Ported from perkins-setback.web.app/app.js. Differences from the standalone tool:
 *  - config (asset base URL, geocoder key, contact URL) comes from window.PerkinsMWC
 *    (wp_localize_script) instead of hardcoded paths;
 *  - all element ids are prefixed perkins-mwc-* to be page-embed-safe;
 *  - wired on DOMContentLoaded (button + Enter) rather than inline onclick.
 * Distance: nearest point on the bundled OSM coastline (ocean, gulf, bays, ICW).
 * Verdicts: assets/zones.json — per-material, per-manufacturer published setback provisions.
 */
(function () {
	var CFG = window.PerkinsMWC || {};
	var FT_PER_M = 3.28084;
	var SEGS = null, ZONES = null, map, marker, line;

	var dataReady = Promise.all([
		fetch(CFG.assetsUrl + 'coastline.geojson').then(function (r) { return r.json(); }),
		fetch(CFG.assetsUrl + 'zones.json').then(function (r) { return r.json(); }),
	]).then(function (res) {
		var coast = res[0];
		ZONES = res[1];
		var geoms = coast.type === 'GeometryCollection'
			? coast.geometries
			: coast.features.map(function (f) { return f.geometry; });
		var segs = [];
		for (var gi = 0; gi < geoms.length; gi++) {
			var c = geoms[gi].coordinates;
			for (var i = 0; i + 1 < c.length; i++) {
				segs.push(c[i][0], c[i][1], c[i + 1][0], c[i + 1][1]);
			}
		}
		SEGS = segs;
	});

	function nearestSaltwater(lat, lon) {
		var kx = 111320 * Math.cos((lat * Math.PI) / 180), ky = 110540;
		var best = Infinity, bx = 0, by = 0;
		for (var win = 0.6; win <= 6; win *= 2) {
			for (var i = 0; i < SEGS.length; i += 4) {
				var ax = SEGS[i], ay = SEGS[i + 1], cx = SEGS[i + 2], cy = SEGS[i + 3];
				if (Math.abs(ax - lon) > win || Math.abs(ay - lat) > win) continue;
				var px = (lon - ax) * kx, py = (lat - ay) * ky;
				var vx = (cx - ax) * kx, vy = (cy - ay) * ky;
				var L2 = vx * vx + vy * vy;
				var t = L2 ? Math.max(0, Math.min(1, (px * vx + py * vy) / L2)) : 0;
				var dx = px - t * vx, dy = py - t * vy;
				var d = dx * dx + dy * dy;
				if (d < best) { best = d; bx = ax + (t * vx) / kx; by = ay + (t * vy) / ky; }
			}
			if (best < Infinity) break;
		}
		return { meters: Math.sqrt(best), nearest: [by, bx] };
	}

	function loadGmaps() {
		return new Promise(function (resolve, reject) {
			if (window.google && window.google.maps && window.google.maps.Geocoder) return resolve();
			var s = document.createElement('script');
			s.src = 'https://maps.googleapis.com/maps/api/js?key=' + encodeURIComponent(CFG.gmapsKey) +
				'&loading=async&callback=__perkinsMwcGm';
			window.__perkinsMwcGm = function () { resolve(); };
			s.onerror = function () { reject(new Error('Could not load the map service.')); };
			document.head.appendChild(s);
		});
	}

	function geocode(addr) {
		return new Promise(function (resolve, reject) {
			new google.maps.Geocoder().geocode(
				{
					address: addr,
					componentRestrictions: { country: 'US' },
					bounds: new google.maps.LatLngBounds(
						{ lat: 24.3, lng: -87.7 }, { lat: 31.2, lng: -79.7 }),
				},
				function (res, status) {
					if (status === 'OK' && res && res.length) resolve(res[0]);
					else reject(new Error(status === 'ZERO_RESULTS'
						? 'Address not found — try adding city and ZIP.'
						: 'Geocoding failed (' + status + ').'));
				}
			);
		});
	}

	function fmtDist(m) {
		var ft = m * FT_PER_M;
		return ft < 5280
			? Math.round(ft).toLocaleString() + ' ft'
			: (ft / 5280).toFixed(1) + ' mi';
	}

	function esc(s) {
		return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) {
			return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c];
		});
	}

	function verdictFor(material, meters) {
		var ft = meters * FT_PER_M;
		var rows = [], anyVoid = false, anyCond = false;
		for (var i = 0; i < material.provisions.length; i++) {
			var p = material.provisions[i], state = 'ok';
			if (p.void_within_ft != null && ft < p.void_within_ft) state = 'void';
			else if (p.conditional_within_ft != null && ft < p.conditional_within_ft) state = 'cond';
			if (state === 'void') anyVoid = true;
			if (state === 'cond') anyCond = true;
			rows.push({ mfr: p.manufacturer, state: state, note: p.note });
		}
		var cls = anyVoid ? 'void' : anyCond ? 'cond' : 'ok';
		var label = anyVoid ? 'Warranty VOID for some brands'
			: anyCond ? 'Conditional — check brand terms' : 'Warranty-safe';
		return { cls: cls, label: label, rows: rows };
	}

	function check() {
		var input = document.getElementById('perkins-mwc-addr');
		var status = document.getElementById('perkins-mwc-status');
		var result = document.getElementById('perkins-mwc-result');
		var go = document.getElementById('perkins-mwc-go');
		var addr = (input.value || '').trim();
		if (!addr) { status.innerHTML = '<p class="err">Enter an address first.</p>'; return; }
		go.disabled = true;
		status.innerHTML = '<p class="spin">Locating and measuring…</p>';
		result.innerHTML = '';
		dataReady
			.then(loadGmaps)
			.then(function () { return geocode(addr); })
			.then(function (g) {
				var lat = g.geometry.location.lat(), lon = g.geometry.location.lng();
				var ns = nearestSaltwater(lat, lon);
				var meters = ns.meters, nearest = ns.nearest;

				if (!map) {
					map = L.map('perkins-mwc-map');
					L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png',
						{ attribution: '© OpenStreetMap' }).addTo(map);
				}
				if (marker) map.removeLayer(marker);
				if (line) map.removeLayer(line);
				marker = L.marker([lat, lon]).addTo(map).bindPopup(g.formatted_address);
				line = L.polyline([[lat, lon], nearest], { color: '#ef3c1a', dashArray: '6 6' }).addTo(map);
				map.fitBounds(L.latLngBounds([[lat, lon], nearest]).pad(0.5));

				var cards = ZONES.materials.map(function (m) {
					var v = verdictFor(m, meters);
					var rows = v.rows.map(function (r) {
						var word = r.state === 'ok' ? 'Covered' : r.state === 'cond' ? 'Conditional' : 'Void';
						return '<tr><td>' + esc(r.mfr) + '</td><td class="' + r.state + '">' + word +
							'</td><td class="note">' + esc(r.note) + '</td></tr>';
					}).join('');
					return '<div class="verdict"><h2>' + esc(m.name) + ' — <span class="' + v.cls + '">' +
						v.label + '</span></h2><p class="note" style="margin-bottom:8px">' + esc(m.blurb) +
						'</p><table><tr><th>Manufacturer</th><th>At your distance</th><th>Provision</th></tr>' +
						rows + '</table></div>';
				}).join('');

				result.innerHTML =
					'<div class="verdict"><h2>' + esc(g.formatted_address) + '</h2>' +
					'<p class="dist">Distance to mapped salt water: <strong>' + fmtDist(meters) + '</strong></p>' +
					(ZONES.banner ? '<div class="advisory">' + ZONES.banner + '</div>' : '') +
					'<div class="advisory">On a canal or waterway that connects to the ocean or Intracoastal? ' +
					'Manufacturers treat tidal canals as salt water — if your home is canal-front, use the ' +
					'waterfront (most protective) recommendation regardless of the distance shown.</div></div>' +
					cards +
					'<a class="cta" href="' + esc(CFG.contactUrl) + '" target="_blank" rel="noopener">' +
					'Get a free quote with the right material for your home →</a>';
				status.innerHTML = '';
			})
			.catch(function (e) { status.innerHTML = '<p class="err">' + esc(e.message || e) + '</p>'; })
			.then(function () { go.disabled = false; });
	}

	document.addEventListener('DOMContentLoaded', function () {
		var go = document.getElementById('perkins-mwc-go');
		var input = document.getElementById('perkins-mwc-addr');
		if (go) go.addEventListener('click', check);
		if (input) input.addEventListener('keydown', function (e) { if (e.key === 'Enter') check(); });
	});
})();
