<?php
/**
 * Render a shortcode outside WordPress, to SEE the HTML rather than trust that it parses.
 *
 * CI has no PHP, so this is a manual gate — but `php -l` passing is not evidence that a table
 * has rows in it, and a shortcode that renders an empty section fails silently on a live page.
 *
 *   docker run --rm -v "$PWD/wp-plugin/perkins-metal-warranty:/p:ro" \
 *       -v "$PWD/wp-plugin/perkins-metal-warranty/tests:/h:ro" \
 *       php:8.3-cli php /h/render.php metal_roof_guide
 *
 * The stubs below are only what the two shortcodes actually call. Escaping is stubbed to the
 * real htmlspecialchars so the output is comparable to what WordPress emits.
 */
define('ABSPATH', __DIR__);
$GLOBALS['shortcodes'] = [];
function add_shortcode($t,$f){ $GLOBALS['shortcodes'][$t]=$f; }
function add_action(...$a){} function add_options_page(...$a){} function register_setting(...$a){}
function settings_fields(...$a){} function submit_button(...$a){}
function wp_enqueue_style(...$a){} function wp_enqueue_script(...$a){} function wp_localize_script(...$a){}
function get_option($k,$d=''){ return $d; }
function plugin_dir_path($f){ return dirname($f).'/'; }
function plugin_dir_url($f){ return 'https://example.test/wp-content/plugins/perkins-metal-warranty/'; }
function esc_html($s){ return htmlspecialchars((string)$s, ENT_QUOTES); }
function esc_attr($s){ return htmlspecialchars((string)$s, ENT_QUOTES); }
function esc_url($s){ return htmlspecialchars((string)$s, ENT_QUOTES); }
require ( is_dir( '/p' ) ? '/p' : dirname( __DIR__ ) ) . '/perkins-metal-warranty.php';
echo call_user_func($GLOBALS['shortcodes'][$argv[1]]);
