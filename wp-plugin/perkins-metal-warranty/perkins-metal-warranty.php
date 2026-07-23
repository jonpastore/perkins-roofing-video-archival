<?php
/**
 * Plugin Name: Perkins Metal Roof Warranty Checker
 * Description: [metal_warranty_checker] shortcode — a coastal metal-roof warranty tool. Geocodes a
 *              South Florida address, measures straight-line distance to mapped salt water, and shows
 *              which metal roofing materials keep their manufacturer warranty valid at that location
 *              (per-manufacturer void / conditional / covered provisions). Ported from the standalone
 *              perkins-setback.web.app tool; the coastline + warranty-provision data ship as plugin
 *              assets. Tidal/brackish canals are handled by an on-tool advisory (manufacturers treat
 *              them as salt water regardless of the mapped distance).
 * Version:     1.0.0
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

define( 'PERKINS_MWC_VERSION', '1.0.0' );
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
			This tool estimates straight-line distance to mapped open salt water (Atlantic, Gulf, bays,
			and the Intracoastal) and summarizes published manufacturer warranty setback provisions. It
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
		<p>Place the tool on any page or post with the shortcode <code>[metal_warranty_checker]</code>.</p>
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
