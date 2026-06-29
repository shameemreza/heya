# Connect a WordPress site

Heya can connect to a development or staging WordPress and WooCommerce site and
act on it through the official Abilities API: discover what the site can do,
then run those abilities to query orders, update status, manage products, and
more. Discovery (listing the site's abilities) flows; running an ability or making a REST call asks for your approval first.

## Connect

1. In WordPress, create an application password: Users, your profile,
   Application Passwords. Copy the password it gives you.
2. Run `heya wp connect`. Enter the site URL, your username, the environment
   (dev or staging, production is not allowed), and the application password.
   Heya stores the password in its locked credentials file, never in the
   config.
3. Heya confirms by listing a few of the site's abilities.

## What you can do

- `wp_abilities` lists the site's abilities (read-only).
- `wp_run_ability` runs one by name, for example `woocommerce/orders-query` or
  `woocommerce/orders-update-status`. Each run asks for your approval. The
  site's own permission checks decide what is allowed.
- `wp_rest` calls the WooCommerce REST API for anything not exposed as an
  ability, for example `/wc/v3/orders`. Every call asks for your approval,
  the same as running an ability.

As the site registers more abilities (subscriptions, memberships), Heya gains
them automatically, with no Heya update.

## The MCP option

If your site runs the `wordpress-mcp` plugin, you can connect Heya to its
Streamable-HTTP endpoint instead, since Heya already supports http MCP servers
with a bearer token. See the MCP guide for adding a server.

## Safety

Connect development or staging sites only, not production. Heya acts as the
user behind the application password and can do only what that user can.
