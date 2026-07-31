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
	// SEGS   open salt water — ocean, gulf, bays, ICW (natural=coastline)
	// TIDAL_SEGS  inland reaches that carry salt, built by scripts/build_tidal_layer.py.
	//        "tagged" = OSM says tidal/salt outright, or the reach opens onto the coastline.
	//        "inferred" = connected to tidewater without crossing a mapped control structure.
	//        Only tagged water moves a verdict; OSM barrier coverage is incomplete and a false
	//        "void" tells a homeowner their warranty is dead when it is not.
	var SEGS = null, TIDAL_SEGS = null, TIDAL_INF = null, ZONES = null, map, marker, line, line2;

	function flatten(doc) {
		var geoms = doc.type === 'GeometryCollection'
			? doc.geometries
			: doc.features.map(function (f) { return f.geometry; });
		var out = { tagged: [], inferred: [] };
		for (var gi = 0; gi < geoms.length; gi++) {
			var g = geoms[gi], c = g.coordinates;
			var bucket = g.confidence === 'inferred' ? out.inferred : out.tagged;
			for (var i = 0; i + 1 < c.length; i++) {
				bucket.push(c[i][0], c[i][1], c[i + 1][0], c[i + 1][1]);
			}
		}
		return out;
	}

	var dataReady = Promise.all([
		fetch(CFG.assetsUrl + 'coastline.geojson').then(function (r) { return r.json(); }),
		fetch(CFG.assetsUrl + 'zones.json').then(function (r) { return r.json(); }),
		// The tidal layer is additive: if it fails to load the tool still answers on open water.
		fetch(CFG.assetsUrl + 'tidal.geojson')
			.then(function (r) { return r.ok ? r.json() : null; })
			.catch(function () { return null; }),
	]).then(function (res) {
		ZONES = res[1];
		SEGS = flatten(res[0]).tagged;
		var tidal = res[2] ? flatten(res[2]) : { tagged: [], inferred: [] };
		TIDAL_SEGS = tidal.tagged;
		TIDAL_INF = tidal.inferred;
	});

	function nearestIn(segs, lat, lon) {
		var kx = 111320 * Math.cos((lat * Math.PI) / 180), ky = 110540;
		var best = Infinity, bx = 0, by = 0;
		if (!segs || !segs.length) return { meters: Infinity, nearest: null };
		for (var win = 0.6; win <= 6; win *= 2) {
			for (var i = 0; i < segs.length; i += 4) {
				var ax = segs[i], ay = segs[i + 1], cx = segs[i + 2], cy = segs[i + 3];
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
		return { meters: Math.sqrt(best), nearest: best < Infinity ? [by, bx] : null };
	}

	/* Open salt water and CONFIRMED tidal water both count toward the verdict. An INFERRED reach
	 * is reported separately and never moves the verdict — see the note in build_tidal_layer.py. */
	function nearestSaltwater(lat, lon) {
		var coast = nearestIn(SEGS, lat, lon);
		var tidal = nearestIn(TIDAL_SEGS, lat, lon);
		var inferred = nearestIn(TIDAL_INF, lat, lon);
		var useTidal = tidal.meters < coast.meters;
		var eff = useTidal ? tidal : coast;
		return {
			meters: eff.meters,
			nearest: eff.nearest,
			kind: useTidal ? 'tidal' : 'open',
			coast: coast,
			tidal: tidal,
			inferred: inferred
		};
	}

	function loadGmaps() {
		return new Promise(function (resolve, reject) {
			if (window.google && window.google.maps && window.google.maps.Geocoder) return resolve();
			var settled = false;
			function fail(msg) {
				if (settled) { return; }
				settled = true;
				reject(new Error(msg));
			}
			// A rejected referrer / bad key downloads the script with HTTP 200 and then reports
			// through gm_authFailure — onerror never fires and the callback is never invoked, so
			// without these two guards the tool spins on "Locating and measuring..." forever with
			// nothing shown to the user. Observed live on staging as RefererNotAllowedMapError.
			window.gm_authFailure = function () {
				fail('The map service rejected this site (the address key is not authorised for ' +
					'this domain). Call us and we will check the address for you.');
			};
			var s = document.createElement('script');
			s.src = 'https://maps.googleapis.com/maps/api/js?key=' + encodeURIComponent(CFG.gmapsKey) +
				'&loading=async&callback=__perkinsMwcGm';
			window.__perkinsMwcGm = function () { if (!settled) { settled = true; resolve(); } };
			s.onerror = function () { fail('Could not load the map service.'); };
			// Backstop for any other silent failure mode.
			setTimeout(function () { fail('The map service did not respond. Please try again.'); }, 12000);
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
				if (line2) { map.removeLayer(line2); line2 = null; }
				marker = L.marker([lat, lon]).addTo(map).bindPopup(g.formatted_address);
				line = L.polyline([[lat, lon], nearest], { color: '#ef3c1a', dashArray: '6 6' })
					.addTo(map).bindPopup(ns.kind === 'tidal' ? 'Nearest tidal water' : 'Nearest open salt water');
				var bounds = L.latLngBounds([[lat, lon], nearest]);
				// A possible tidal reach gets its own, visibly different line — it is a question,
				// not a finding, so it must not look like the measured answer.
				var inf = ns.inferred;
				var showInf = inf.nearest && inf.meters < meters;
				if (showInf) {
					line2 = L.polyline([[lat, lon], inf.nearest],
						{ color: '#41B1E5', dashArray: '3 8', weight: 2 })
						.addTo(map).bindPopup('Possible tidal canal — unconfirmed');
					bounds.extend(inf.nearest);
				}
				map.fitBounds(bounds.pad(0.5));

				var cards = ZONES.materials.map(function (m) {
					var v = verdictFor(m, meters);
					// Second verdict only when an unconfirmed reach is nearer AND it would actually
					// change the answer — otherwise it is noise on the page.
					var vInf = showInf ? verdictFor(m, inf.meters) : null;
					var differs = vInf && vInf.cls !== v.cls;
					var rows = v.rows.map(function (r, idx) {
						var word = r.state === 'ok' ? 'Covered' : r.state === 'cond' ? 'Conditional' : 'Void';
						var alt = '';
						if (differs) {
							var ir = vInf.rows[idx];
							var iword = ir.state === 'ok' ? 'Covered'
								: ir.state === 'cond' ? 'Conditional' : 'Void';
							alt = ir.state === r.state ? '<span class="note">same</span>'
								: '<span class="' + ir.state + '">' + iword + '</span>';
						}
						return '<tr><td>' + esc(r.mfr) + '</td><td class="' + r.state + '">' + word +
							'</td>' + (differs ? '<td>' + alt + '</td>' : '') +
							'<td class="note">' + esc(r.note) + '</td></tr>';
					}).join('');
					return '<div class="verdict"><h2>' + esc(m.name) + ' — <span class="' + v.cls + '">' +
						v.label + '</span>' +
						(differs ? ' <span class="note">(if that canal is tidal: <span class="' +
							vInf.cls + '">' + vInf.label + '</span>)</span>' : '') +
						'</h2><p class="note" style="margin-bottom:8px">' + esc(m.blurb) +
						'</p><table><tr><th>Manufacturer</th><th>At your distance</th>' +
						(differs ? '<th>If tidal</th>' : '') +
						'<th>Provision</th></tr>' + rows + '</table></div>';
				}).join('');

				// What the measurement rests on, in plain words, plus the second reading when the
				// two layers disagree — a homeowner should see WHICH water we measured to.
				var distLine = ns.kind === 'tidal'
					? 'Distance to salt water: <strong>' + fmtDist(meters) +
					  '</strong> <span class="note">(a tidal waterway — open ocean/ICW is ' +
					  fmtDist(ns.coast.meters) + ')</span>'
					: 'Distance to open salt water: <strong>' + fmtDist(meters) + '</strong>' +
					  (ns.tidal.nearest && ns.tidal.meters < Infinity
						? ' <span class="note">(nearest confirmed tidal waterway ' +
						  fmtDist(ns.tidal.meters) + ')</span>' : '');

				var infBlock = '';
				if (showInf) {
					var infFt = inf.meters * FT_PER_M;
					infBlock =
						'<div class="advisory"><strong>There is water about ' + fmtDist(inf.meters) +
						' away that may be tidal.</strong> Map data shows it connecting toward the ' +
						'ocean or Intracoastal without a lock or salinity structure in between, but ' +
						'that connection is not confirmed and control structures are not always ' +
						'mapped. If it is tidal, manufacturers treat it as salt water and the ' +
						'stricter reading below applies at ' + Math.round(infFt).toLocaleString() +
						' ft. Worth a look on site before choosing the material.</div>';
				}

				result.innerHTML =
					'<div class="verdict"><h2>' + esc(g.formatted_address) + '</h2>' +
					'<p class="dist">' + distLine + '</p>' +
					(ZONES.banner ? '<div class="advisory">' + ZONES.banner + '</div>' : '') +
					infBlock +
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
