<?php
/**
 * Plugin Name: Perkins Metal Roof Warranty Checker
 * Description: [metal_warranty_checker] shortcode — a coastal metal-roof warranty tool. Geocodes a
 *              South Florida address, measures straight-line distance to mapped salt water, and shows
 *              which metal roofing materials keep their manufacturer warranty valid at that location
 *              (per-manufacturer void / conditional / covered provisions). Ported from the standalone
 *              perkins-setback.web.app tool; the coastline, tidal-water and warranty-provision data
 *              ship as plugin assets. Tidal/brackish reaches count toward the distance when OSM
 *              confirms them; a merely inferred reach raises a caveat and never moves a verdict
 *              (see docs/WARRANTY_TOOL_TIDAL_LAYER.md).
 *              [metal_roof_guide] shortcode — the educational page: the manufacturer warranty
 *              comparison rendered from the SAME zones.json the checker uses, plus published
 *              wind-uplift approvals and the aluminum-roof example videos.
 * Version:     1.5.1
 * Author:      DeGenito
 *
 * SETUP (one manual step): the geocoder uses the Google Maps JavaScript API. Its browser key is
 * HTTP-referrer-restricted, so the WordPress domain must be added to the key's allowed referrers in
 * Google Cloud Console (APIs & Services -> Credentials). Set the key under Settings -> Metal Warranty
 * Checker. Until the referrer is authorized the UI renders but geocoding returns an error.
 */

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}

define( 'PERKINS_MWC_VERSION', '1.5.1' );
define( 'PERKINS_MWC_URL', plugin_dir_url( __FILE__ ) );

// Default browser key (referrer-restricted). Overridable in Settings so a per-site key can be used
// without editing the plugin.
const PERKINS_MWC_DEFAULT_KEY = 'AIzaSyDU-ju5UwRWnKe7VRiUM1SiWwZ_Qf19NWI';

function perkins_mwc_gmaps_key() {
	$k = trim( (string) get_option( 'perkins_mwc_gmaps_key', '' ) );
	return $k !== '' ? $k : PERKINS_MWC_DEFAULT_KEY;
}

function perkins_mwc_contact_url() {
	$u = trim( (string) get_option( 'perkins_mwc_contact_url', '' ) );
	return $u !== '' ? $u : 'https://perkinsroofing.net/contact/';
}

/**
 * [metal_warranty_checker] — renders the tool. Enqueues Leaflet (CDN), the plugin CSS/JS, and
 * localizes the asset base URL + geocoder key so the JS can load the bundled coastline/zones data.
 */
function perkins_mwc_shortcode() {
	wp_enqueue_style(
		'leaflet',
		'https://unpkg.com/leaflet@1.9.4/dist/leaflet.css',
		[],
		'1.9.4'
	);
	wp_enqueue_script(
		'leaflet',
		'https://unpkg.com/leaflet@1.9.4/dist/leaflet.js',
		[],
		'1.9.4',
		true
	);
	wp_enqueue_style(
		'perkins-mwc',
		PERKINS_MWC_URL . 'assets/checker.css',
		[ 'leaflet' ],
		PERKINS_MWC_VERSION
	);
	wp_enqueue_script(
		'perkins-mwc',
		PERKINS_MWC_URL . 'assets/checker.js',
		[ 'leaflet' ],
		PERKINS_MWC_VERSION,
		true
	);
	wp_localize_script(
		'perkins-mwc',
		'PerkinsMWC',
		[
			'assetsUrl'  => PERKINS_MWC_URL . 'assets/',
			'version'    => PERKINS_MWC_VERSION,
			'gmapsKey'   => perkins_mwc_gmaps_key(),
			'contactUrl' => perkins_mwc_contact_url(),
		]
	);

	ob_start();
	?>
	<div class="perkins-mwc">
		<p class="perkins-mwc-lede">
			How close is your home to salt water? Enter your address — we'll measure the distance and
			show which metal roofing materials keep their <strong>manufacturer warranty</strong> valid
			at your location.
		</p>
		<div class="perkins-mwc-search">
			<input id="perkins-mwc-addr" type="text"
				placeholder="Enter your address (e.g. 575 NW 152nd St, Miami, FL)" />
			<button id="perkins-mwc-go" type="button">Check my address</button>
		</div>
		<div id="perkins-mwc-status"></div>
		<div id="perkins-mwc-map"></div>
		<div class="perkins-mwc-result" id="perkins-mwc-result"></div>
		<p class="perkins-mwc-foot">
			This tool estimates straight-line distance to salt water — mapped open water (Atlantic,
			Gulf, bays and the Intracoastal) plus tidal and brackish rivers and canals, which
			manufacturers treat the same way — and summarizes published manufacturer warranty setback
			provisions. Tidal waterways are mapped for South Florida only. Where map data suggests a
			nearby canal may be tidal but does not confirm it, we say so rather than assume it. This
			is a guide, not a warranty determination — final material eligibility is governed by each
			manufacturer's current written warranty for your specific product and site. Map data ©
			OpenStreetMap contributors.
		</p>
	</div>
	<?php
	return ob_get_clean();
}
add_shortcode( 'metal_warranty_checker', 'perkins_mwc_shortcode' );

// ---------------------------------------------------------------------------
// [metal_roof_guide] — the educational page content (warranty comparison + wind uplift)
// ---------------------------------------------------------------------------

/**
 * Read a bundled JSON asset. Returns [] on any failure — a guide section that cannot load its
 * data renders nothing rather than fataling the whole page.
 */
function perkins_mwc_asset( $name ) {
	$path = plugin_dir_path( __FILE__ ) . 'assets/' . $name;
	if ( ! is_readable( $path ) ) {
		return [];
	}
	$data = json_decode( (string) file_get_contents( $path ), true );
	return is_array( $data ) ? $data : [];
}

/**
 * How one manufacturer treats one material near salt water, as a short phrase.
 *
 * `void_within_ft` and `conditional_within_ft` are the same two fields the checker reads out of
 * zones.json, so the guide table and the tool can never disagree about a manufacturer — there is
 * one dataset, not a prose copy of one. A copy is how a warranty table goes stale silently.
 *
 * Returns the checker's OWN verdict classes (ok/void/cond) so red means the same thing on both,
 * without a second palette to keep in sync.
 */
function perkins_mwc_provision_phrase( $p ) {
	$void = $p['void_within_ft'] ?? null;
	$cond = $p['conditional_within_ft'] ?? null;
	if ( $void ) {
		return [ 'void', sprintf( 'No warranty within %s ft', number_format( (int) $void ) ) ];
	}
	if ( $cond ) {
		return [ 'cond', sprintf( 'Covered at any distance; conditions within %s ft', number_format( (int) $cond ) ) ];
	}
	return [ 'ok', 'Covered at any distance' ];
}

function perkins_mwc_guide_shortcode() {
	wp_enqueue_style(
		'perkins-mwc',
		PERKINS_MWC_URL . 'assets/checker.css',
		[],
		PERKINS_MWC_VERSION
	);

	$zones  = perkins_mwc_asset( 'zones.json' );
	$guide  = perkins_mwc_asset( 'guide.json' );
	$videos = [];
	foreach ( $guide['videos'] ?? [] as $v ) {
		$videos[ $v['section'] ][] = $v;
	}

	ob_start();
	?>
	<div class="perkins-mwc perkins-mwg">

		<section class="perkins-mwg-section">
			<h2>Which metal keeps its warranty near salt water</h2>
			<p>Every manufacturer below publishes a setback: a distance from salt or brackish water
				inside which the paint or perforation warranty is reduced, conditioned, or void
				outright. The distances differ by <em>brand</em>, not just by metal, which is why two
				quotes for &ldquo;a metal roof&rdquo; can carry completely different coverage at the
				same address.</p>
			<?php foreach ( $zones['materials'] ?? [] as $m ) : ?>
				<h3><?php echo esc_html( $m['name'] ); ?></h3>
				<p class="perkins-mwg-blurb"><?php echo esc_html( $m['blurb'] ); ?></p>
				<table class="perkins-mwg-table">
					<thead>
						<tr><th>Manufacturer</th><th>Near salt water</th><th>Published provision</th></tr>
					</thead>
					<tbody>
					<?php foreach ( $m['provisions'] ?? [] as $p ) : ?>
						<?php list( $cls, $phrase ) = perkins_mwc_provision_phrase( $p ); ?>
						<tr>
							<td><?php echo esc_html( $p['manufacturer'] ); ?></td>
							<td><span class="<?php echo esc_attr( $cls ); ?>"><?php echo esc_html( $phrase ); ?></span></td>
							<td><?php echo esc_html( $p['note'] ); ?></td>
						</tr>
					<?php endforeach; ?>
					</tbody>
				</table>
			<?php endforeach; ?>
			<p class="perkins-mwg-note">Distances are straight-line to mapped salt water, which
				includes tidal and brackish canals &mdash; manufacturers treat a brackish canal behind
				the house the same as the ocean. Check a specific address with the
				<strong>warranty checker</strong>; these tables are the published provisions behind
				its answer.</p>
		</section>

		<?php if ( ! empty( $guide['uplift'] ) ) : ?>
		<section class="perkins-mwg-section">
			<h2>Wind uplift: not all standing seam is the same roof</h2>
			<p>&ldquo;Standing seam&rdquo; on a quote can mean a <strong>snap lock</strong> panel that
				clips together, or a <strong>mechanically seamed</strong> panel that is bent closed over
				concealed clips. They look similar from the street and they do not perform alike. These
				are the manufacturer&rsquo;s own published approval numbers:</p>
			<table class="perkins-mwg-table">
				<thead>
					<tr>
						<th>Panel</th><th>Attachment</th>
						<th>Design pressure</th><th>Equivalent wind</th><th></th>
					</tr>
				</thead>
				<tbody>
				<?php foreach ( $guide['uplift'] as $u ) : ?>
					<tr>
						<td><strong><?php echo esc_html( $u['panel'] ); ?></strong>
							<?php if ( ! empty( $u['hvhz'] ) ) : ?>
								<span class="ok">HVHZ approved</span>
							<?php endif; ?>
						</td>
						<td><?php echo esc_html( $u['attachment'] ); ?></td>
						<td><?php echo esc_html( $u['psf'] ); ?> psf</td>
						<td><?php echo esc_html( $u['mph'] ); ?> mph</td>
						<td><?php echo esc_html( $u['note'] ); ?></td>
					</tr>
				<?php endforeach; ?>
				</tbody>
			</table>
			<p class="perkins-mwg-note"><?php echo esc_html( $guide['_sources']['uplift'] ?? '' ); ?></p>
			<?php echo perkins_mwc_video_list( $videos['uplift'] ?? [] ); // phpcs:ignore WordPress.Security.EscapeOutput.OutputNotEscaped — escaped inside ?>
		</section>
		<?php endif; ?>

		<?php if ( ! empty( $videos['aluminum'] ) ) : ?>
		<section class="perkins-mwg-section">
			<h2>Aluminum on the water</h2>
			<p>Aluminum does not rust. That is the whole reason it is the coastal answer: it is the one
				material class above that every manufacturer here warranties at <em>any</em> distance
				from salt water, including beachfront &mdash; and, seamed, it reaches essentially the
				same uplift numbers as steel. Most brands ask for a twice-yearly fresh-water rinse near
				the water, and they mean it: keep the records.</p>
			<?php echo perkins_mwc_video_list( $videos['aluminum'] ); // phpcs:ignore WordPress.Security.EscapeOutput.OutputNotEscaped — escaped inside ?>
		</section>
		<?php endif; ?>

		<p class="perkins-mwg-cta">
			<a href="<?php echo esc_url( perkins_mwc_contact_url() ); ?>">Talk to Perkins Roofing about your address</a>
		</p>
	</div>
	<?php
	return ob_get_clean();
}
add_shortcode( 'metal_roof_guide', 'perkins_mwc_guide_shortcode' );

/**
 * Video links for one guide section. Plain anchors, not iframe embeds: an embed per section costs
 * a third-party script on page load and the page is meant to be read, not watched.
 */
function perkins_mwc_video_list( $videos ) {
	if ( ! $videos ) {
		return '';
	}
	$out = '<ul class="perkins-mwg-videos">';
	foreach ( $videos as $v ) {
		$out .= sprintf(
			'<li><a href="%s" target="_blank" rel="noopener">%s</a> &mdash; %s</li>',
			esc_url( $v['url'] ),
			esc_html( $v['title'] ),
			esc_html( $v['why'] )
		);
	}
	return $out . '</ul>';
}

// ---------------------------------------------------------------------------
// Settings — Google Maps key + contact URL (Settings -> Metal Warranty Checker)
// ---------------------------------------------------------------------------

add_action( 'admin_menu', function () {
	add_options_page(
		'Metal Warranty Checker',
		'Metal Warranty Checker',
		'manage_options',
		'perkins-mwc',
		'perkins_mwc_settings_page'
	);
} );

add_action( 'admin_init', function () {
	register_setting( 'perkins_mwc', 'perkins_mwc_gmaps_key', [ 'sanitize_callback' => 'sanitize_text_field' ] );
	register_setting( 'perkins_mwc', 'perkins_mwc_contact_url', [ 'sanitize_callback' => 'esc_url_raw' ] );
} );

function perkins_mwc_settings_page() {
	?>
	<div class="wrap">
		<h1>Metal Warranty Checker</h1>
		<p>Two shortcodes, placed on any page or post:</p>
		<ul>
			<li><code>[metal_warranty_checker]</code> &mdash; the address lookup tool (map + per-address verdict).</li>
			<li><code>[metal_roof_guide]</code> &mdash; the educational page: the manufacturer warranty
				comparison, published wind-uplift approvals, and the aluminum-roof example videos. Needs
				no API key and renders server-side, so it is readable by search engines.</li>
		</ul>
		<p><strong>Google Maps key:</strong> the geocoder needs this WordPress domain added to the key's
			HTTP-referrer allowlist in Google Cloud Console (APIs &amp; Services → Credentials). Leave
			blank to use the built-in default key.</p>
		<form method="post" action="options.php">
			<?php settings_fields( 'perkins_mwc' ); ?>
			<table class="form-table">
				<tr>
					<th scope="row"><label for="perkins_mwc_gmaps_key">Google Maps API key</label></th>
					<td><input name="perkins_mwc_gmaps_key" id="perkins_mwc_gmaps_key" type="text"
						class="regular-text" value="<?php echo esc_attr( get_option( 'perkins_mwc_gmaps_key', '' ) ); ?>"
						placeholder="(using built-in default)" /></td>
				</tr>
				<tr>
					<th scope="row"><label for="perkins_mwc_contact_url">Quote / contact URL</label></th>
					<td><input name="perkins_mwc_contact_url" id="perkins_mwc_contact_url" type="url"
						class="regular-text" value="<?php echo esc_attr( get_option( 'perkins_mwc_contact_url', '' ) ); ?>"
						placeholder="https://perkinsroofing.net/contact/" /></td>
				</tr>
			</table>
			<?php submit_button(); ?>
		</form>
	</div>
	<?php
}
