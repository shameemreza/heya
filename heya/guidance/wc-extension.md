---
name: wc-extension
description: WooCommerce extension essentials. Declare HPOS and Cart and Checkout Blocks compatibility, use CRUD objects instead of post meta, log with wc_get_logger, and name it for WooCommerce.
---

# WooCommerce extension essentials

Every rule in this file applies to every WooCommerce extension you write or
modify. Read `wp-plugin-structure` alongside this file; WooCommerce extensions
are WordPress plugins first.

## Compatibility declarations

Declare both High-Performance Order Storage (HPOS) compatibility and Cart and
Checkout Blocks compatibility before WooCommerce initialises. HPOS compatibility
is required for listing on the WooCommerce marketplace.

Both declarations use `FeaturesUtil::declare_compatibility`, called from the
`before_woocommerce_init` action:

```php
add_action( 'before_woocommerce_init', 'myplugin_declare_wc_compatibility' );

function myplugin_declare_wc_compatibility() {
    if ( class_exists( \Automattic\WooCommerce\Utilities\FeaturesUtil::class ) ) {
        \Automattic\WooCommerce\Utilities\FeaturesUtil::declare_compatibility(
            'custom_order_tables',
            __FILE__,
            true
        );
        \Automattic\WooCommerce\Utilities\FeaturesUtil::declare_compatibility(
            'cart_checkout_blocks',
            __FILE__,
            true
        );
    }
}
```

Use feature id `'custom_order_tables'` for HPOS and `'cart_checkout_blocks'`
for block-based Cart and Checkout. Pass `false` as the third argument only when
your extension is genuinely incompatible and you want WooCommerce to warn the
merchant.

The second argument must resolve to your main plugin file. If the callback
lives in an included file, `__FILE__` resolves to that file's path and the
declaration silently fails; pass a stored reference to the main file instead.

## CRUD objects, not raw post meta

WooCommerce order and product data is managed through CRUD objects. Never read
or write that data through raw WordPress post meta functions.

Use `WC_Order` and `WC_Product` getters and setters:

```php
// Wrong: reads from post meta directly.
$value = get_post_meta( $order_id, '_my_field', true );
update_post_meta( $order_id, '_my_field', $new_value );

// Right: uses the CRUD layer.
$order = wc_get_order( $order_id );
$value = $order->get_meta( '_my_field' );
$order->update_meta_data( '_my_field', $new_value );
$order->save();
```

Under HPOS, orders are stored in custom tables rather than `wp_posts`. Code
that calls `get_post_meta` on an order ID will break or return stale data in
that mode. `WC_Order::get_meta` and `WC_Order::update_meta_data` work correctly
regardless of the underlying storage.

The same principle applies to `WC_Product`: use `$product->get_meta()`,
`$product->update_meta_data()`, and `$product->save()` rather than
`get_post_meta` / `update_post_meta` on the product ID.

## Logging

Log with `wc_get_logger`, not `error_log`. WooCommerce logs are written to the
`wc-logs` directory, are accessible from WooCommerce > Status > Logs, and can
be filtered by source:

```php
$logger = wc_get_logger();
$logger->info(
    'Payment confirmed for order ' . $order->get_id(),
    [ 'source' => 'myplugin' ]
);
$logger->error(
    'API call failed: ' . $e->getMessage(),
    [ 'source' => 'myplugin' ]
);
```

Always pass a `source` key so the log entry can be filtered and identified
quickly. Available levels: `debug`, `info`, `notice`, `warning`, `error`,
`critical`, `alert`, `emergency`.

## Cart and Checkout Blocks integration

The classic shortcode-based Cart and Checkout pages are deprecated in favour of
the block-based equivalents. Provide a Blocks integration alongside any existing
shortcode support; do not rely on shortcodes alone.

Implement `Automattic\WooCommerce\Blocks\Integrations\IntegrationInterface` to
register block-scoped scripts and data. The interface requires `get_name`,
`initialize`, `get_script_handles`, `get_editor_script_handles`, and
`get_script_data`. Implement all five; omitting any one leaves an abstract
method unimplemented and PHP will fatal:

```php
use Automattic\WooCommerce\Blocks\Integrations\IntegrationInterface;

class MyPlugin_Blocks_Integration implements IntegrationInterface {

    public function get_name() {
        return 'myplugin';
    }

    public function initialize() {
        wp_register_script(
            'myplugin-blocks',
            plugin_dir_url( __FILE__ ) . 'build/blocks.js',
            [],
            '1.0.0',
            true
        );
    }

    public function get_script_handles() {
        return [ 'myplugin-blocks' ];
    }

    public function get_editor_script_handles() {
        return [ 'myplugin-blocks' ];
    }

    public function get_script_data() {
        return [ 'ajaxUrl' => admin_url( 'admin-ajax.php' ) ];
    }
}
```

Register the integration on the `woocommerce_blocks_loaded` action. Note that
the `Package::container()` call below reaches into the WooCommerce Blocks
internal dependency-injection container, which is not a documented stable
public API and has changed across Blocks releases; check the WooCommerce Blocks
compatibility and extensibility docs for your target version before relying on
it:

```php
add_action( 'woocommerce_blocks_loaded', function() {
    if ( ! class_exists( 'Automattic\WooCommerce\Blocks\Package' ) ) {
        return;
    }
    \Automattic\WooCommerce\Blocks\Package::container()
        ->get( \Automattic\WooCommerce\Blocks\Integrations\IntegrationRegistry::class )
        ->register( new MyPlugin_Blocks_Integration() );
} );
```

For deeper Checkout customisation, WooCommerce Blocks exposes three additional
extension points:

- **Checkout filters** (`registerCheckoutFilters` in JS): modify labels, totals,
  and item data shown in the Checkout block.
- **Slot fills** (`ExperimentalOrderMeta`, `ExperimentalOrderLocalPickupPackages`,
  and others): render custom content inside block areas using React slot/fill.
- **Store API extension** (`ExtendSchema`): add custom data to Store API
  endpoints so the Checkout block can read extension-specific values.

## Naming and plugin headers

A WooCommerce extension's display name must end in "for WooCommerce". Examples:
"Shipping Labels for WooCommerce", "Custom Fields for WooCommerce". This
convention signals to merchants what the extension requires and is enforced on
the WooCommerce marketplace.

Declare the WooCommerce version you have tested against in the plugin header:

```php
/**
 * Plugin Name: Custom Fields for WooCommerce
 * Description: Adds custom fields to WooCommerce orders.
 * Requires Plugins: woocommerce
 * WC requires at least: 8.0
 * WC tested up to: 9.4
 */
```

The version numbers above are illustrative; set them to the WooCommerce versions you actually test against and update them with each release.

`WC requires at least` and `WC tested up to` are read by WooCommerce to surface
compatibility notices to merchants. Keep them current with each release. Use
`Requires Plugins: woocommerce` (a standard WordPress plugin header) to declare
the hard dependency so WordPress can warn merchants before they activate the
extension without WooCommerce.
