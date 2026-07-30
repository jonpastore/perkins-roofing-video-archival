<?php
/**
 * Plugin Name: Perkins Roofing JSON-LD Injector
 * Description: Registers _perkins_jsonld + the Rank Math SEO meta keys for the REST API and echoes
 *              the stored JSON-LD in wp_head. Also serves /llms.txt and the AI-crawler robots rules.
 * Version:     1.3.0
 * Author:      DeGenito
 *
 * GENERATED — do not edit. The source of truth is wp-mu-plugin/perkins-jsonld.php; everything below
 * this header is a verbatim copy of it. tests/test_wp_plugin_parity.py fails if they drift.
 * Install ONE form only: this plugin (wp-admin upload) OR the mu-plugin. Both = duplicate schema.
 */

/**
 * Post types that may carry JSON-LD. 'post' = articles. 'avada_portfolio' + 'page' = project
 * write-ups: the generated portfolio uses the CPT while the nine PUBLIC projects are pages
 * under /portfolio/, and until that URL question is settled both have to work. Registering
 * for one type only is why a project page could store no schema at all — WP rejects meta on
 * an unregistered key, and wp_head skipped anything that was not a singular 'post'.
 */
define( 'PERKINS_JSONLD_POST_TYPES', [ 'post', 'avada_portfolio', 'page' ] );

add_action( 'init', function () {
    foreach ( PERKINS_JSONLD_POST_TYPES as $type ) {
        register_post_meta( $type, '_perkins_jsonld', [
            'single'        => true,
            'type'          => 'string',
            'show_in_rest'  => true,
            'auth_callback' => function () { return current_user_can( 'edit_posts' ); },
        ] );
    }
} );

/**
 * Register Rank Math's SEO meta keys for the REST API so Application-Password
 * publishing can set the focus keyword + SEO title/description. Rank Math stores
 * these as normal post-meta but does not expose them over REST, and its own
 * admin REST route (rankmath/v1/updateMeta) is blocked by the managed-hosting
 * WAF for non-browser calls — so we register them here and write via wp/v2.
 */
add_action( 'init', function () {
    $rank_math_keys = [ 'rank_math_focus_keyword', 'rank_math_title', 'rank_math_description' ];
    foreach ( $rank_math_keys as $key ) {
      foreach ( PERKINS_JSONLD_POST_TYPES as $type ) {
        register_post_meta( $type, $key, [
            'single'        => true,
            'type'          => 'string',
            'show_in_rest'  => true,
            'auth_callback' => function () { return current_user_can( 'edit_posts' ); },
        ] );
      }
    }
} );

add_action( 'wp_head', function () {
    if ( ! is_singular( PERKINS_JSONLD_POST_TYPES ) ) {
        return;
    }
    $raw = get_post_meta( get_the_ID(), '_perkins_jsonld', true );
    if ( empty( $raw ) ) {
        return;
    }
    // Escape </script> sequences to prevent early tag close.
    $safe = str_replace( '</', '<\/', $raw );
    echo '<script type="application/ld+json">' . $safe . '</script>' . "\n";
} );
// Fallback route: only reached when no physical llms.txt exists at the webroot —
// a static file is served by the web server before WordPress ever parses the request.
add_action( 'parse_request', function () {
    $path = parse_url( $_SERVER['REQUEST_URI'], PHP_URL_PATH );
    if ( $path !== '/llms.txt' ) {
        return;
    }
    $content = get_option( 'perkins_llms_txt' );
    if ( empty( $content ) ) {
        status_header( 404 );
        exit;
    }
    header( 'Content-Type: text/plain; charset=utf-8' );
    echo $content;
    exit;
} );

// Explicit AI-crawler allowlist appended to WordPress's virtual robots.txt (filter-based —
// does not touch Rank Math's sitemap/robots config; no-op if a physical robots.txt exists).
add_filter( 'robots_txt', function ( $output ) {
    $bots = [
        'GPTBot', 'ChatGPT-User', 'OAI-SearchBot',
        'ClaudeBot', 'Claude-User', 'Claude-SearchBot',
        'PerplexityBot', 'Perplexity-User', 'Google-Extended',
    ];
    foreach ( $bots as $bot ) {
        $output .= "\nUser-agent: {$bot}\nAllow: /\n";
    }
    return $output;
} );

add_action( 'rest_api_init', function () {
    register_rest_route( 'perkins/v1', '/llms-txt', [
        'methods'             => 'POST',
        'permission_callback' => function () { return current_user_can( 'edit_posts' ); },
        'callback'            => function ( $request ) {
            $content = $request->get_param( 'content' );
            if ( empty( $content ) ) {
                return new WP_Error( 'missing_content', 'Content is required.', [ 'status' => 400 ] );
            }
            update_option( 'perkins_llms_txt', $content, false );
            // A pre-existing static llms.txt at the webroot shadows the fallback route above,
            // so also (best-effort) write the physical file the web server actually serves.
            $file_written = false;
            $target = ABSPATH . 'llms.txt';
            if ( is_writable( ABSPATH ) && ( ! file_exists( $target ) || is_writable( $target ) ) ) {
                $file_written = false !== file_put_contents( $target, $content );
            }
            return [ 'ok' => true, 'bytes' => strlen( $content ), 'file_written' => $file_written ];
        },
    ] );

    register_rest_route( 'perkins/v1', '/llms-txt', [
        'methods'             => 'GET',
        'permission_callback' => function () { return current_user_can( 'edit_posts' ); },
        'callback'            => function () {
            $content = get_option( 'perkins_llms_txt', '' );
            return [ 'content' => $content, 'bytes' => strlen( $content ) ];
        },
    ] );
} );
