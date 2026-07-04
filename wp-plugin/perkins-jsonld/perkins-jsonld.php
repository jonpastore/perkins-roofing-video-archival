<?php
/**
 * Plugin Name: Perkins Roofing JSON-LD Injector
 * Description: Registers the _perkins_jsonld post-meta (so the REST API accepts it) and echoes the
 *              stored JSON-LD inside a <script type="application/ld+json"> tag in wp_head for singular
 *              posts. WordPress strips <script> from post content, so this is the safe injection point.
 * Version:     1.0.0
 * Author:      DeGenito
 *
 * NOTE: This is the uploadable-plugin form of wp-mu-plugin/perkins-jsonld.php. Prefer the mu-plugin
 * (drop into wp-content/mu-plugins/) in production; this plugin exists so it can be installed via the
 * WordPress admin UI (Plugins → Add New → Upload) where filesystem access isn't available.
 */

add_action( 'init', function () {
    register_post_meta( 'post', '_perkins_jsonld', [
        'single'        => true,
        'type'          => 'string',
        'show_in_rest'  => true,
        'auth_callback' => function () { return current_user_can( 'edit_posts' ); },
    ] );
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
