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
