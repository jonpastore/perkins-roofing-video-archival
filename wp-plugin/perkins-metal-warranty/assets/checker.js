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
	//        "tagged"   = OSM tags THAT reach tidal=yes/salt=yes. Moves a verdict.
	//        "mapped"   = FDEP classifies this water body Class III-Marine / Class II AND the reach
	//                     connects to tidewater. Moves a verdict; carries the water body's name.
	//        "inferred" = reached from tidewater without crossing a mapped structure, including
	//                     reaches that merely open onto the coastline. NEVER moves a verdict —
	//                     OSM barrier coverage is incomplete and a false "void" tells a homeowner
	//                     their warranty is dead when it is not.
	var SEGS = null, TIDAL_SEGS = null, TIDAL_META = null, TIDAL_INF = null;
	var ZONES = null, COVERAGE = null;
	var map, marker, line, line2;
	var VER = CFG.version ? ('?ver=' + encodeURIComponent(CFG.version)) : '';

	function flatten(doc, defaultBucket) {
		var geoms = doc.type === 'GeometryCollection'
			? doc.geometries
			: (doc.features || []).map(function (f) { return f.geometry; });
		// `meta` runs parallel to `tagged`, one entry per segment, so when a measured segment wins
		// we can quote the actual reading rather than say "confirmed" and leave them wondering.
		var out = { tagged: [], meta: [], inferred: [] };
		for (var gi = 0; gi < geoms.length; gi++) {
			var g = geoms[gi], c = g && g.coordinates;
			if (!c || !c.length) continue;
			// FAIL SAFE: only an explicit "tagged" earns the verdict-moving bucket. `confidence` is
			// a foreign member on a GeoJSON geometry and gets stripped by mapshaper/turf/minifiers;
			// if that happens every reach must degrade to a caveat, never silently become
			// authoritative salt water.
			// Water a gauge MEASURED as fresh belongs in neither bucket: it is not salt water, and
			// raising it as "may be tidal" would warn about water we know is fine.
			if (g.confidence === 'fresh') continue;
			// A gauge reading, an OSM tag and FDEP's marine class all move a verdict; bare
			// connectivity never does. Keep this list in step with VERDICT_MOVING in
			// scripts/build_tidal_layer.py — a test asserts the two agree.
			var verdictMoving = g.confidence === 'measured' || g.confidence === 'tagged'
				|| g.confidence === 'mapped'
				|| (!g.confidence && defaultBucket === 'tagged');
			var bucket = verdictMoving ? out.tagged : out.inferred;
			for (var i = 0; i + 1 < c.length; i++) {
				bucket.push(c[i][0], c[i][1], c[i + 1][0], c[i + 1][1]);
				// A measurement outranks a classification. In practice a reach never carries both:
				// build_tidal_layer.py sets `wbid` only on `mapped` and `measurement` only on
				// `measured`/`fresh`, and the gauge pass relabels `mapped` out of the class. The
				// ordering is kept so it stays correct if that ever changes.
				if (verdictMoving) out.meta.push(g.measurement || g.wbid || null);
			}
		}
		return out;
	}

	/* Is this address inside the area the tidal layer actually covers? Outside it we know nothing,
	 * and must not imply "no tidal water near you". Both layers are statewide as of 2026-07-31;
	 * this stays because the bbox is read from the asset, so a narrower rebuild re-arms the caveat.
	 * NOTE: inside the bbox the layer is still clipped to 3 mi of coastline, which this test does
	 * not model — see REACH_MI in scripts/build_tidal_layer.py. */
	function inTidalCoverage(lat, lon) {
		if (!COVERAGE) return false;
		return lat >= COVERAGE[0] && lon >= COVERAGE[1] && lat <= COVERAGE[2] && lon <= COVERAGE[3];
	}

	// Geometry is fetched on the first check, not on page load, so simply landing on the page costs
	// nothing. `?ver=` follows the plugin version so a corrected layer is not served from a stale
	// browser or CDN cache.
	//
	// The tidal layer is 22 MB of JSON and the host sends NO content-encoding (verified against the
	// live URL: no gzip, no br), so it would go over the wire uncompressed. The build writes a
	// pre-gzipped twin and we inflate it here with DecompressionStream — native since Chrome 80 /
	// Safari 16.4 / Firefox 113, no library — which puts it back at 2.9 MB, the size the layer was
	// before NHD hydrography closed the polygon-canal hole.
	//
	// ⚠️ ALWAYS falls back to the plain .json: an old browser, a host that will not serve .gz, or a
	// truncated file must degrade to a slow load, never to a wrong answer. The tidal layer being
	// absent silently downgrades every waterfront address to the open-water measurement, which is
	// exactly the false CLEAR this layer exists to prevent — so failure has to be loud in the log.
	function fetchMaybeGzipped(name) {
		var plain = function () {
			return fetch(CFG.assetsUrl + name + VER)
				.then(function (r) { return r.ok ? r.json() : null; });
		};
		if (typeof DecompressionStream !== 'function') return plain();
		return fetch(CFG.assetsUrl + name + '.gz' + VER).then(function (r) {
			if (!r.ok || !r.body) throw new Error('no gz');
			return new Response(
				r.body.pipeThrough(new DecompressionStream('gzip'))).json();
		}).catch(function (e) {
			if (window.console) console.warn('perkins-mwc: gz load failed, falling back', e);
			return plain();
		});
	}

	var dataReady = null;
	function loadData() {
		if (dataReady) return dataReady;
		dataReady = Promise.all([
			fetch(CFG.assetsUrl + 'coastline.geojson' + VER).then(function (r) { return r.json(); }),
			fetch(CFG.assetsUrl + 'zones.json' + VER).then(function (r) { return r.json(); }),
			// The tidal layer is additive: if it fails to load the tool still answers on open water.
			fetchMaybeGzipped('tidal.geojson').catch(function () { return null; }),
		]).then(function (res) {
			ZONES = res[1];
			SEGS = flatten(res[0], 'tagged').tagged;
			var tidal = { tagged: [], inferred: [] };
			// A 200 carrying valid JSON of the WRONG shape (a WP error body, a half-written
			// rebuild) must not take the open-water answer down with it.
			try {
				if (res[2]) {
					tidal = flatten(res[2], 'inferred');
					var bb = res[2]._coverage_bbox;
					if (bb) {
						COVERAGE = bb.split(',').map(parseFloat);
						if (COVERAGE.length !== 4 || COVERAGE.some(isNaN)) COVERAGE = null;
					}
				}
			} catch (e) {
				tidal = { tagged: [], inferred: [] };
				COVERAGE = null;
			}
			TIDAL_SEGS = tidal.tagged;
			TIDAL_META = tidal.meta;
			TIDAL_INF = tidal.inferred;
		}).catch(function (e) {
			// Do not latch a rejection: one flaky fetch would otherwise break the tool for the
			// rest of the page view, with every later click replaying the same error.
			dataReady = null;
			throw e;
		});
		return dataReady;
	}

	function nearestIn(segs, lat, lon) {
		var kx = 111320 * Math.cos((lat * Math.PI) / 180), ky = 110540;
		var best = Infinity, bx = 0, by = 0, bi = -1;
		if (!segs || !segs.length) return { meters: Infinity, nearest: null, index: -1 };
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
				if (d < best) { best = d; bx = ax + (t * vx) / kx; by = ay + (t * vy) / ky; bi = i / 4; }
			}
			if (best < Infinity) break;
		}
		return { meters: Math.sqrt(best), nearest: best < Infinity ? [by, bx] : null, index: bi };
	}

	/* Open salt water and CONFIRMED tidal water both count toward the verdict. An INFERRED reach
	 * is reported separately and never moves the verdict — see the note in build_tidal_layer.py. */
	function nearestSaltwater(lat, lon) {
		var coast = nearestIn(SEGS, lat, lon);
		var tidal = nearestIn(TIDAL_SEGS, lat, lon);
		var inferred = nearestIn(TIDAL_INF, lat, lon);
		var useTidal = tidal.meters < coast.meters;
		var eff = useTidal ? tidal : coast;
		var reading = (useTidal && TIDAL_META && tidal.index >= 0)
			? TIDAL_META[tidal.index] : null;
		return {
			meters: eff.meters,
			nearest: eff.nearest,
			kind: useTidal ? 'tidal' : 'open',
			reading: reading,
			coast: coast,
			tidal: tidal,
			inferred: inferred
		};
	}

	// ⚠️ MEMOISED, and that is load-bearing, not an optimisation. The input's focus handler warms
	// the geocoder and check() loads it again; unmemoised, a visitor who clicks into the box, types
	// and hits Check before the API finishes downloading gets TWO calls, and the second one sees
	// `window.google.maps.Geocoder` still undefined, injects a SECOND Maps <script>, and overwrites
	// window.__perkinsMwcGm with its own resolver. The duplicate bootstrap logs
	// "Element with name gmp-internal-* already defined" and leaves a Geocoder that never invokes
	// its callback — the tool sits on "Finding the address…" forever with no error.
	//
	// Measured on live staging 2026-08-07: focus-then-immediate-click HUNG 2 of 3 runs; the same
	// click with a 6 s gap answered 2 of 2. That is a real visitor typing quickly, not a test
	// artifact. Same latching shape as `dataReady` above, and cleared on failure for the same
	// reason: one flaky load must not break the tool for the rest of the page view.
	var gmapsReady = null;
	function loadGmaps() {
		if (gmapsReady) return gmapsReady;
		gmapsReady = new Promise(function (resolve, reject) {
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
			// No `libraries=places`: only the Geocoder is used now. See the note where the
			// typeahead used to live.
			s.src = 'https://maps.googleapis.com/maps/api/js?key=' + encodeURIComponent(CFG.gmapsKey) +
				'&loading=async&callback=__perkinsMwcGm';
			window.__perkinsMwcGm = function () { if (!settled) { settled = true; resolve(); } };
			s.onerror = function () { fail('Could not load the map service.'); };
			// Backstop for any other silent failure mode.
			setTimeout(function () { fail('The map service did not respond. Please try again.'); }, 12000);
			document.head.appendChild(s);
		});
		// Do not latch a FAILURE: a flaky load would otherwise poison every later attempt on this
		// page view, which is exactly the trap `dataReady` documents.
		gmapsReady.catch(function () { gmapsReady = null; });
		return gmapsReady;
	}

	function geocode(addr) {
		return new Promise(function (resolve, reject) {
			// NOTHING else bounds this. Every other step in check() has a terminal state, but the
			// Geocoder callback is Google's to invoke, and when the API is in a bad state it simply
			// never fires — no error, no rejection, just "Finding the address…" until the visitor
			// gives up. The memoised loadGmaps above removes the cause we know about; this bounds
			// the ones we do not, because a wrong answer is worse than a spinner but a silent
			// spinner is worse than a stated failure.
			var settled = false;
			var backstop = setTimeout(function () {
				if (settled) { return; }
				settled = true;
				reject(new Error('The address service did not respond. Please try again.'));
			}, 20000);
			new google.maps.Geocoder().geocode(
				{
					address: addr,
					componentRestrictions: { country: 'US' },
					bounds: new google.maps.LatLngBounds(
						{ lat: 24.3, lng: -87.7 }, { lat: 31.2, lng: -79.7 }),
				},
				function (res, status) {
					if (settled) { return; }        // a late callback after the backstop fired
					settled = true;
					clearTimeout(backstop);
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
		result.innerHTML = '';
		// Every phase reports. The silent spinner is what made a 40-minute outage invisible, so
		// each step gets a terminal state and a failure names the step it died in.
		var steps = [], phase = '';
		function step(label) {
			if (phase) steps.push('✓ ' + phase);
			phase = label;
			status.innerHTML = '<p class="spin">' +
				(steps.length ? steps.join('<br>') + '<br>' : '') + '→ ' + label + '…</p>';
		}
		step('Loading coastline and tidal water');
		loadData()
			.then(function () { step('Finding the address'); return loadGmaps(); })
			.then(function () { return geocode(addr); })
			.then(function (g) {
				step('Measuring to the nearest salt water');
				var lat = g.geometry.location.lat(), lon = g.geometry.location.lng();
				var ns = nearestSaltwater(lat, lon);
				step(ns.reading ? 'Checking salinity readings for this waterway'
					: 'Building your warranty summary');
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
				// `nearest` is null when no water is in range at all (an out-of-state address).
				// Leaflet throws on a null latlng, and the raw TypeError used to land in the
				// status box in front of the homeowner.
				var bounds = L.latLngBounds([[lat, lon], [lat, lon]]);
				if (nearest) {
					line = L.polyline([[lat, lon], nearest], { color: '#ef3c1a', dashArray: '6 6' })
						.addTo(map).bindPopup(ns.kind === 'tidal' ? 'Nearest tidal water' : 'Nearest open salt water');
					bounds = L.latLngBounds([[lat, lon], nearest]);
				}
				// A possible tidal reach gets its own, visibly different line — it is a question,
				// not a finding, so it must not look like the measured answer.
				var inf = ns.inferred;
				var showInf = inf.nearest && inf.meters < meters && inTidalCoverage(lat, lon);
				if (showInf) {
					line2 = L.polyline([[lat, lon], inf.nearest],
						{ color: '#41B1E5', dashArray: '3 8', weight: 2 })
						.addTo(map).bindPopup('Possible tidal canal — unconfirmed');
					bounds.extend(inf.nearest);
				}
				map.fitBounds(bounds.pad(0.5));

				// Each material is computed ONCE and rendered twice: as a one-line verdict in the
				// sticky summary column and as a full provision table in the detail column. Deriving
				// both from the same `verdictFor` call is what stops the two columns from ever
				// disagreeing about the same address.
				var matViews = ZONES.materials.map(function (m) {
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
					return {
						name: m.name,
						cls: v.cls,
						label: v.label,
						infCls: differs ? vInf.cls : null,
						infLabel: differs ? vInf.label : null,
						html: '<div class="verdict"><h2>' + esc(m.name) + ' — <span class="' + v.cls + '">' +
							v.label + '</span>' +
							(differs ? ' <span class="note">(if that canal is tidal: <span class="' +
								vInf.cls + '">' + vInf.label + '</span>)</span>' : '') +
							'</h2><p class="note" style="margin-bottom:8px">' + esc(m.blurb) +
							'</p><table><tr><th>Manufacturer</th><th>At your distance</th>' +
							(differs ? '<th>If tidal</th>' : '') +
							'<th>Provision</th></tr>' + rows + '</table></div>'
					};
				});
				var cards = matViews.map(function (x) { return x.html; }).join('');
				var summaryRows = matViews.map(function (x) {
					return '<li><span class="perkins-mwc-sum-mat">' + esc(x.name) + '</span>' +
						'<span class="' + x.cls + '">' + x.label + '</span>' +
						(x.infCls ? '<span class="note">if tidal: <span class="' + x.infCls + '">' +
							x.infLabel + '</span></span>' : '') + '</li>';
				}).join('');

				// What the measurement rests on, in plain words, plus the second reading when the
				// two layers disagree — a homeowner should see WHICH water we measured to.
				var covered = inTidalCoverage(lat, lon);
				var r = ns.reading;
				// Say WHY we call it salt water. A measured reading beats any adjective; a state
				// classification beats "a tidal waterway", which tells a homeowner nothing they
				// can check. `r` is a gauge reading when it has us_cm, an FDEP class when it has
				// water_class — both are evidence a customer can look up.
				var basis;
				if (r && r.us_cm != null) {
					basis = ' <span class="note">(measured at ' + Math.round(r.us_cm).toLocaleString() +
						' µS/cm — ' + esc(r.station_name) + ', USGS ' + esc(r.station) + ', ' +
						fmtDist(r.distance_m) + ' along the waterway)</span>';
				} else if (r && r.water_class) {
					basis = ' <span class="note">(' + esc(r.name || 'this waterway') +
						' — classified ' +
						(r.water_class === '3M' ? 'Class III-Marine' :
							r.water_class === '2' ? 'Class II marine (shellfish)' :
								'marine, Class ' + esc(r.water_class)) +
						' by the Florida DEP; open ocean/ICW is ' + fmtDist(ns.coast.meters) +
						')</span>';
				} else {
					basis = ' <span class="note">(a tidal waterway — open ocean/ICW is ' +
						fmtDist(ns.coast.meters) + ')</span>';
				}
				var distLine = ns.kind === 'tidal'
					? 'Distance to salt water: <strong>' + fmtDist(meters) + '</strong>' + basis
					: 'Distance to open salt water: <strong>' + fmtDist(meters) + '</strong>' +
					  (covered && ns.tidal.nearest
						? ' <span class="note">(nearest confirmed tidal waterway ' +
						  fmtDist(ns.tidal.meters) + ')</span>'
						: !covered
							? ' <span class="note">(tidal canals and rivers are not mapped at ' +
							  'this address — we cannot check them here)</span>' : '');

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

				// Two columns: the ANSWER on the left, the evidence for it on the right. The left
				// column sticks, so the distance and the per-material verdict a visitor came for stay
				// on screen while they scroll the provision tables that justify them. Below 860px the
				// grid collapses to one column and the summary simply leads, unpinned.
				result.innerHTML =
					'<div class="perkins-mwc-cols">' +
					'<aside class="perkins-mwc-col-summary"><div class="verdict">' +
					'<h2>' + esc(g.formatted_address) + '</h2>' +
					'<p class="dist">' + distLine + '</p>' +
					'<ul class="perkins-mwc-summary">' + summaryRows + '</ul>' +
					'<a class="cta" href="' + esc(CFG.contactUrl) + '" target="_blank" rel="noopener">' +
					'Get a free quote with the right material for your home →</a>' +
					'</div></aside>' +
					'<div class="perkins-mwc-col-detail">' +
					(ZONES.banner ? '<div class="advisory">' + ZONES.banner + '</div>' : '') +
					infBlock +
					'<div class="advisory">On a canal or waterway that connects to the ocean or Intracoastal? ' +
					'Manufacturers treat tidal canals as salt water — if your home is canal-front, use the ' +
					'waterfront (most protective) recommendation regardless of the distance shown.</div>' +
					cards +
					'</div></div>';
				status.innerHTML = '';
			})
			.catch(function (e) {
				status.innerHTML = '<p class="err">' + esc(e.message || e) +
					(phase ? ' <span class="note">(while ' + esc(phase.toLowerCase()) + ')</span>' : '') +
					'</p>';
			})
			.then(function () { go.disabled = false; });
	}

	/* NO TYPEAHEAD ON THE ADDRESS BOX, deliberately. It used to use
	 * `google.maps.places.Autocomplete`, which Google closed to new customers on 2025-03-01 — this
	 * project is one, so every keystroke got REQUEST_DENIED ("you're calling a legacy API, which is
	 * not enabled for your project") and Google painted "This page can't load Google Maps
	 * correctly" over the address field. It never once produced a suggestion; it only ever produced
	 * that dialog, sitting on top of a verdict that was computed correctly underneath it.
	 * Restoring it means Places API (New) + `PlaceAutocompleteElement` + adding
	 * places-backend.googleapis.com to the perkins-setback-widget key's API targets in Terraform.
	 * Until someone decides that is worth the per-session billing, typing the address in full and
	 * pressing the button is the whole interaction, and it works. */

	document.addEventListener('DOMContentLoaded', function () {
		var go = document.getElementById('perkins-mwc-go');
		var input = document.getElementById('perkins-mwc-addr');
		if (go) go.addEventListener('click', check);
		if (input) {
			input.addEventListener('keydown', function (e) { if (e.key === 'Enter') check(); });
			// Warm the geocoder on first focus so it is ready by the time they finish typing, and
			// the page costs nothing for a visitor who never touches the box.
			input.addEventListener('focus', function () {
				loadGmaps().catch(function () {
					/* check() reports any real failure when they actually submit */
				});
			}, { once: true });
		}
	});
})();
