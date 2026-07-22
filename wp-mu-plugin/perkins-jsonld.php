<?php
/**
 * Perkins Roofing — JSON-LD injector (must-use plugin)
 *
 * INSTALL: Drop this file into wp-content/mu-plugins/perkins-jsonld.php
 * WordPress loads mu-plugins automatically — no activation needed.
 *
 * HOW IT WORKS:
 *   1. Registers the post-meta key '_perkins_jsonld' so the WP REST API
 *      accepts writes to it (required for Application Password publishing).
 *   2. On wp_head for singular posts, echoes the stored JSON-LD inside a
 *      <script type="application/ld+json"> tag.  WP strips <script> from
 *      post content, so this mu-plugin is the only safe injection point.
 */

add_action( 'init', function () {
    register_post_meta( 'post', '_perkins_jsonld', [
        'single'        => true,
        'type'          => 'string',
        'show_in_rest'  => true,
        'auth_callback' => function () { return current_user_can( 'edit_posts' ); },
    ] );
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
