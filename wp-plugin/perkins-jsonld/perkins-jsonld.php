<?php
/**
 * Plugin Name: Perkins Roofing JSON-LD Injector
 * Description: Registers the _perkins_jsonld post-meta (so the REST API accepts it) and echoes the
 *              stored JSON-LD inside a <script type="application/ld+json"> tag in wp_head for singular
 *              posts. WordPress strips <script> from post content, so this is the safe injection point.
 *              Also serves /llms.txt via a custom endpoint and provides a REST route to manage it.
 * Version:     1.2.0
 * Author:      DeGenito
 *
 * NOTE: This is the uploadable-plugin form of wp-mu-plugin/perkins-jsonld.php. Prefer the mu-plugin
 * (drop into wp-content/mu-plugins/) in production; this plugin exists so it can be installed via the
 * WordPress admin UI (Plugins -> Add New -> Upload) where filesystem access isn't available.
 */

add_action( 'init', function () {
    $keys = [
        '_perkins_jsonld',
        'rank_math_focus_keyword',
        'rank_math_title',
        'rank_math_description',
    ];

    foreach ( $keys as $key ) {
        register_post_meta( 'post', $key, [
            'single'        => true,
            'type'          => 'string',
            'show_in_rest'  => true,
            'auth_callback' => function () { return current_user_can( 'edit_posts' ); },
        ] );
    }
} );

add_action( 'wp_head', function () {
    if ( ! is_singular( 'post' ) ) {
        return;
    }
    $raw = get_post_meta( get_the_ID(), '_perkins_jsonld', true );
    if ( empty( $raw ) ) {
        return;
    }
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
