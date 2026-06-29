---
name: wp-blocks
description: WordPress block development. block.json metadata, apiVersion 3, static, dynamic, and interactive blocks, wrapper attributes, and deprecations so saved markup stays valid.
---

# WordPress block development

WordPress blocks are registered with a `block.json` metadata file and built
with `@wordpress/scripts` or `@wordpress/create-block`. The three block models
(static, dynamic, interactive) share the same registration pattern but differ
in where and how they produce markup.

## block.json metadata

Every block must have a `block.json` file at the root of the block directory.
This file is the single source of truth for the block's metadata, scripts,
styles, and capabilities.

```json
{
  "$schema": "https://schemas.wp.org/trunk/block.json",
  "apiVersion": 3,
  "name": "my-plugin/card",
  "title": "Card",
  "category": "text",
  "description": "A simple card block.",
  "version": "1.0.0",
  "textdomain": "my-plugin",
  "editorScript": "file:./index.js",
  "editorStyle": "file:./index.css",
  "style": "file:./style-index.css",
  "render": "file:./render.php"
}
```

Use `apiVersion: 3`. This is the current standard and ensures the block works
correctly inside the iframed block editor introduced in WordPress 6.3.

Register the block in PHP with `register_block_type_from_metadata`, passing
the directory path that contains `block.json`. Do not hand-register scripts,
styles, or attributes separately when `block.json` already declares them.

```php
function my_plugin_register_blocks(): void {
    register_block_type_from_metadata( __DIR__ . '/build/card' );
}
add_action( 'init', 'my_plugin_register_blocks' );
```

If the plugin contains multiple blocks, loop over the build directory rather
than calling `register_block_type_from_metadata` once per block by hand.

## Static blocks

A static block serializes its markup into post content. The editor saves the
output of the `save` function; the saved HTML is what gets rendered on the
front end.

In the editor, wrap the block's root element with `useBlockProps`:

```js
import { useBlockProps } from '@wordpress/block-editor';

export function Edit( { attributes } ) {
    const blockProps = useBlockProps();
    return <div { ...blockProps }>{ attributes.content }</div>;
}
```

In the save function, use `useBlockProps.save` so the wrapper attributes
written to content match what the editor applied:

```js
export function Save( { attributes } ) {
    const blockProps = useBlockProps.save();
    return <div { ...blockProps }>{ attributes.content }</div>;
}
```

If wrapper attributes differ between the editor and the saved markup, the block
will be flagged as invalid on load.

## Dynamic blocks

A dynamic block renders its output at request time. Add a `render` key in
`block.json` pointing to a `render.php` file, or supply a `render_callback`
when calling `register_block_type_from_metadata`.

In `render.php`, use `get_block_wrapper_attributes` to get the block's
wrapper attributes (class, style, and any custom attributes declared in
`block.json`) and apply them to the outermost element:

```php
// render.php receives $attributes, $content, and $block.
$wrapper_attrs = get_block_wrapper_attributes();
?>
<div <?php echo $wrapper_attrs; // phpcs:ignore WordPress.Security.EscapeOutput.OutputNotEscaped ?>>
    <?php echo wp_kses_post( $content ); ?>
</div>
```

`get_block_wrapper_attributes` already returns a safe string; escaping it a
second time will corrupt class names. Every other dynamic value you output must
be escaped: use `esc_html`, `esc_url`, `wp_kses_post`, or an equivalent.

The `save` function for a dynamic block should return `null` (or an empty
element as a placeholder). Nothing meaningful is stored in post content.

## Interactive blocks

Interactive blocks add client-side behavior through the Interactivity API.
Declare a `viewScriptModule` (not `viewScript`) in `block.json` to load the
module:

```json
{
  "viewScriptModule": "file:./view.js"
}
```

Use `viewScript` only for classic (non-module) scripts. Prefer
`viewScriptModule` for new blocks because it loads as a native ES module and
integrates with the Interactivity API's store.

In the render path, add `wp-interactive` and `data-wp-*` directives to the
wrapper. The Interactivity API reads these at runtime.

## Inner blocks

When a block accepts inner blocks, replace `useBlockProps` with
`useInnerBlocksProps` in the editor. This attaches both the block wrapper
attributes and the inner block drop zone in one call:

```js
import { useBlockProps, useInnerBlocksProps } from '@wordpress/block-editor';

export function Edit() {
    const blockProps = useBlockProps();
    const innerBlocksProps = useInnerBlocksProps( blockProps, {
        allowedBlocks: [ 'core/paragraph', 'core/heading' ],
    } );
    return <div { ...innerBlocksProps } />;
}
```

In the save function, use `useInnerBlocksProps.save` to write the inner block
serialization token:

```js
import { useBlockProps, useInnerBlocksProps } from '@wordpress/block-editor';

export function Save() {
    const blockProps = useBlockProps.save();
    const innerBlocksProps = useInnerBlocksProps.save( blockProps );
    return <div { ...innerBlocksProps } />;
}
```

## Deprecations

When a saved block's markup changes in an incompatible way, the block becomes
invalid for content saved under the old format. Fix this by adding a
`deprecated` entry rather than changing the existing save function in place.

Add entries newest to oldest: the deprecation array is checked in order, and
the first matching entry is used to migrate the content.

```js
const deprecated = [
    {
        // Previous version of the save function.
        attributes: { content: { type: 'string' } },
        save( { attributes } ) {
            return <p>{ attributes.content }</p>;
        },
    },
];

// JS-side registration: pairs with block.json metadata registered on the PHP side
// via register_block_type_from_metadata. The name must match the "name" field in block.json.
registerBlockType( 'my-plugin/card', {
    // ...
    deprecated,
} );
```

Include a `migrate` function when attributes also changed shape. Without it,
WordPress applies the old save output directly, which works only when attributes
are unchanged.

Keep deprecated entries in the bundle permanently. Removing them leaves
existing content invalid for any user who saved content under that format.

## Build and enqueue

Use `@wordpress/scripts` to compile block source files. To scaffold a new block
from scratch, run `npx @wordpress/create-block my-block`, which sets up the
directory structure and configures `@wordpress/scripts` automatically. The standard
`package.json` scripts are:

```json
{
  "scripts": {
    "build": "wp-scripts build",
    "start": "wp-scripts start"
  }
}
```

`wp-scripts build` reads `src/block-name/index.js` (or the entry points
declared in `block.json`) and writes compiled assets to `build/`. Commit the
`build/` directory or generate it in CI before the plugin zip is assembled.

Enqueue is handled automatically when you use `register_block_type_from_metadata`.
Do not call `wp_enqueue_script` or `wp_enqueue_style` for assets already
declared in `block.json`.

## Block plugins

Block plugins follow the standard WordPress plugin guidelines plus the
block-specific guidelines. Key points:

- The plugin must do something useful without requiring a companion theme.
- Blocks must be in the correct category and use meaningful, accurate titles
  and descriptions.
- Do not register blocks on the front end only to suppress their stylesheet.
  Use the `style` vs `editorStyle` split in `block.json` for that.
- Block assets must be escaped and validated the same way as any other plugin
  output. The block editor is not a trusted context.
