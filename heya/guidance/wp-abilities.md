---
name: wp-abilities
description: Make a plugin AI-callable with the WordPress Abilities API. Register an ability with a label, an input and output schema, a permission check, and an execute callback, so agents and Heya can use it.
---

# WordPress Abilities API

The WordPress Abilities API lets you expose a discrete plugin action as a
named, schema-driven operation that AI agents, MCP clients, and tools like
Heya can discover and run. An ability is not a REST endpoint you document
manually; it is a self-describing unit: it carries its own label, description,
input and output schemas, a permission check, and an execute callback. The
platform validates inputs and enforces authorization before your callback runs.

## What an ability is

An ability is a named action registered with `wp_register_ability( $name, $properties )`
on the `abilities_api_init` hook. Once registered, it is discoverable through
REST and MCP without additional configuration.

```php
add_action( 'abilities_api_init', 'myplugin_register_abilities' );

function myplugin_register_abilities() {
    wp_register_ability(
        'myplugin/orders-export',
        [
            'label'              => __( 'Export orders', 'my-plugin' ),
            'description'        => __( 'Export orders to CSV for a given date range.', 'my-plugin' ),
            'input_schema'       => [
                'type'       => 'object',
                'properties' => [
                    'start_date' => [ 'type' => 'string', 'format' => 'date' ],
                    'end_date'   => [ 'type' => 'string', 'format' => 'date' ],
                ],
                'required'   => [ 'start_date', 'end_date' ],
            ],
            'output_schema'      => [
                'type'       => 'object',
                'properties' => [
                    'download_url' => [ 'type' => 'string', 'format' => 'uri' ],
                    'row_count'    => [ 'type' => 'integer' ],
                ],
            ],
            'execute_callback'   => 'myplugin_execute_orders_export',
            'permission_callback' => 'myplugin_can_export_orders',
        ]
    );
}
```

## Required properties

Every ability registration must include all of the following.

**`label`**: a short human-readable name displayed in tool listings.

**`description`**: one sentence that explains what the ability does. Write it
for the agent reading it, not for a developer. The agent uses this to decide
whether to call the ability.

**`input_schema`**: a JSON Schema object that declares every accepted input
field, its type, format, and constraints, and which fields are required. The
platform validates the caller's input against this schema before calling
`execute_callback`. A schema that is too loose lets bad inputs reach your code.

**`output_schema`**: a JSON Schema object that describes the structure
`execute_callback` returns. Agents use this to interpret the result. Keep the
shape flat and predictable.

**`execute_callback`**: the function that does the work. It receives the
validated input array and must return data matching `output_schema`, or a
`WP_Error` on failure.

**`permission_callback`**: called with the raw input before validation. It must
return `true` when the current user is authorized, or a `WP_Error` (or `false`)
when they are not.

## Naming abilities

Name an ability like a REST namespace segment: `myplugin/verb-noun`. Examples:
`myplugin/orders-export`, `myplugin/coupon-create`, `myplugin/report-fetch`.

One ability per discrete action. Do not combine two distinct operations into one
ability with a `mode` parameter; register two abilities instead.

## Permission callback

The `permission_callback` runs before input validation. It receives the raw
input as its only argument and returns `true` or a `WP_Error`.

Match the capability to the action's risk level. A read ability checks a read
capability. A write ability checks the capability the underlying operation
requires. Never skip the permission callback; an ability without one is an
unauthenticated endpoint.

```php
// Wrong: skips authorization entirely.
'permission_callback' => '__return_true',

// Right: checks the capability the action requires.
function myplugin_can_export_orders( $input ) {
    if ( ! current_user_can( 'view_woocommerce_reports' ) ) {
        return new WP_Error(
            'rest_forbidden',
            __( 'You do not have permission to export orders.', 'my-plugin' ),
            [ 'status' => 403 ]
        );
    }
    return true;
}
```

## Execute callback

The `execute_callback` receives the validated and type-cast input array. Return
an array that matches `output_schema`, or a `WP_Error` on failure.

```php
function myplugin_execute_orders_export( $input ) {
    $file = myplugin_generate_csv(
        sanitize_text_field( $input['start_date'] ),
        sanitize_text_field( $input['end_date'] )
    );

    if ( is_wp_error( $file ) ) {
        return $file;
    }

    return [
        'download_url' => $file['url'],
        'row_count'    => $file['count'],
    ];
}
```

Sanitize inputs inside the callback even though the platform has already
validated them against the schema. Validation confirms shape and type; it does
not replace context-specific sanitization.

## Input schema: be precise

A schema that declares only `type: object` with no `properties` offers no
validation. Declare every field the callback reads, mark required fields
explicitly, and use `format` constraints where they apply.

```php
// Wrong: accepts anything, validates nothing.
'input_schema' => [ 'type' => 'object' ],

// Right: declares each field with type and required list.
'input_schema' => [
    'type'       => 'object',
    'properties' => [
        'start_date' => [ 'type' => 'string', 'format' => 'date' ],
        'end_date'   => [ 'type' => 'string', 'format' => 'date' ],
    ],
    'required'   => [ 'start_date', 'end_date' ],
],
```

## Make it discoverable

Set `'meta' => [ 'show_in_rest' => true, 'show_in_mcp' => true ]` in the
registration properties if you want the ability to appear in REST and MCP
discovery. External agents, including Heya's site tools, rely on this metadata
to find and call the ability without additional configuration.

## Before an ability, admin UI only; after, agent-callable

Before: a plugin exposes order export through an admin-only page. An agent
cannot trigger it without screen-scraping or direct database calls.

After: the same logic is wrapped in `myplugin/orders-export`. The agent
discovers it, validates its own input against the schema, calls the ability,
and receives a structured response, all without touching the admin UI.

The underlying business logic does not need to change. Register the ability
as a thin wrapper around the existing function.

## Further reading

Read `wp-plugin-structure` for how to structure the registration code inside
your plugin. Read `wp-security` for sanitization and escaping rules that still
apply inside execute callbacks.
