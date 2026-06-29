---
name: wp-readme-naming
description: WordPress readme.txt, headers, naming, and trademarks. What the readme must contain, how to name a plugin or theme without a trademark problem, and the Directory Guidelines an author must follow.
---

# WordPress readme and naming

Apply the rules in this file to every plugin or theme you submit to WordPress.org or maintain in the Directory. They cover the readme format, naming restrictions, trademark duties, external-service disclosure, and the broader Plugin Directory Guidelines.

## The readme.txt file

The readme.txt is the source of truth the Directory uses to display your plugin or theme listing. Required headers:

```
Contributors: alice, bob
Stable tag: 1.2.3
Requires at least: 6.4
Tested up to: 6.8
Requires PHP: 7.4
License: GPL-2.0-or-later
License URI: https://www.gnu.org/licenses/gpl-2.0.html
```

The version numbers above are illustrative only. Set each header to the versions you actually test against and require; do not copy these values.

Rules for each header:

- **Stable tag** must exactly match the version in your plugin file header (or `style.css` for themes). If they disagree, the Directory cannot resolve which code to serve.
- **Requires at least** and **Tested up to**: set these to the versions you actually tested. Keep Tested up to current; an outdated value suppresses update notices for users who have already upgraded WordPress.
- **Requires PHP**: set it to the minimum PHP version your code actually requires. Do not inflate it.
- **License**: must be GPL-2.0-or-later, GPL-2.0-only, or another GPL-compatible license. Every bundled file and asset must be under a GPL-compatible license.
- Do not add an **Update URI** header to a plugin hosted on WordPress.org. That header is for plugins distributed outside the Directory and tells WordPress where to check for updates. Adding it to a hosted plugin breaks the Directory's update channel.

### Required readme sections

Every plugin readme must contain at least these `== Section ==` blocks:

- **Description**: a clear explanation of what the plugin does.
- **Installation**: how to install and activate it.
- **Changelog**: a version history with dates or release notes. Keep it current.

`Contributors` is not a section. It is a header field in the top block (above `== Description ==`), alongside `Stable tag` and the others. Its value is a comma-separated list of valid WordPress.org usernames. Every username listed must exist and belong to someone who contributed. Do not add a `== Contributors ==` block.

### Tags

Tags help users discover your plugin. A few relevant tags are useful; many are not. Rules:

- Use only tags that accurately describe the plugin.
- Do not include competitor names as tags.
- Do not include affiliate links anywhere in the readme.
- Keyword stuffing (long lists of tangentially related terms) violates Directory Guidelines.

## Naming: plugins and themes

### The trademark rule

Do not name your plugin or theme in a way that is dominated by or leads with a trademark you do not own. The core principle: put your own identifier first and place the trademarked term after a connector word.

Acceptable patterns:

```
my-store-toolkit
acme-payments-for-woocommerce
acme-checkout-with-stripe
acme-salesforce-integration
```

Not acceptable:

```
woocommerce-acme           // leads with the trademark
stripe-by-acme             // trademark still dominates
```

The connector words that work: **for**, **with**, **integration**, or a descriptive phrase that makes clear you are the author and the trademark identifies the platform your plugin extends.

### The WooCommerce slug exception

WooCommerce has an explicit exception in the Directory Guidelines: `wc-` is permitted at the start of a plugin slug. However, the plugin's display name must end in **"for WooCommerce"**, not begin with it.

```
Slug: wc-acme-checkout
Display name: Acme Checkout for WooCommerce
```

### Other naming rules

- No superlatives ("best", "ultimate", "most powerful").
- No redundant words: omit "Free" and "Plugin" from the display name. Users already know it is free (it is in the free Directory) and a plugin (it is listed under Plugins).
- No misleading claims about compatibility with core WordPress features you do not actually extend.
- Respect all applicable trademark and copyright law, not just WooCommerce's. The same connector-word rule applies to every third-party trademark.

## External-service disclosure

If your plugin or theme makes HTTP requests to an external service (analytics, payment processing, license checks, API calls), you must document this in the readme:

- The name of the external service and its purpose.
- What data is sent and under what circumstances.
- A link to the service's terms of service.
- A link to the service's privacy policy.

No tracking of any kind without explicit user opt-in. "Opt-in" means the user actively enables the feature; shipping with tracking on by default is not opt-in.

Example readme section:

```
== External Services ==

This plugin sends the site URL and plugin version to Example API
(https://example.com) when you activate the license. This data is
used solely to validate your license.

Terms of service: https://example.com/terms
Privacy policy: https://example.com/privacy
```

## Plugin Directory Guidelines: author duties

The Plugin Directory Guidelines are the rules every hosted plugin must follow. The list below covers all of them, framed as the duties you owe as an author. Treat every item as required, not optional.

- **GPL-compatible license for everything.** Every file you ship, including JavaScript, CSS, images, and bundled libraries, must be under a GPL-compatible license. Verify the license of every third-party library before bundling.
- **You are responsible for every file.** The developer of record is accountable for all code, actions, and behavior of the plugin, whether written by them or included from a third party.
- **Ship a stable, working version.** The plugin must be complete and functional when you submit it. Provide a working zip with real, usable code. Do not submit a placeholder or "coming soon" shell, and do not reserve a slug for a plugin you have not finished. A stable version must always be available from the Directory page.
- **Human-readable code.** Do not ship minified-only JavaScript or CSS without including the source. The source must be in the repository or linked from the readme.
- **No trialware.** Do not ship a plugin that disables features after a trial period or requires payment to unlock functionality that was previously free.
- **Services documented.** Software as a service is allowed, but any external service your plugin contacts must be documented in the readme as described above.
- **No tracking without consent.** Do not collect user data, site data, or usage telemetry without explicit opt-in.
- **No executable code from third-party systems.** Do not download and run PHP, JavaScript, or binaries from remote servers at runtime, and do not update the plugin from anywhere other than WordPress.org.
- **Credits are opt-in and off by default.** If your plugin adds a "Powered by" credit link or badge on the public site, it must be disabled by default and the site owner must explicitly turn it on.
- **No admin hijacking.** Do not redirect the user away from normal WordPress admin pages without user consent, hijack existing admin notices, or suppress other plugins' notices.
- **No spam.** Do not send unsolicited email or notifications. Keep the readme free of affiliate links, keyword stuffing, and competitor names.
- **Use WordPress-bundled libraries.** Use the copies of jQuery and other libraries that ship with WordPress rather than bundling your own. Respect WordPress defaults for dates, times, and currencies.
- **Release-ready commits with incrementing versions.** Every commit to the hosted SVN repository is a potential release. Commit with intention, increment the version number with each tagged release, and never reuse or skip a version number.
- **Respect trademarks and copyrights.** Apply the naming rules above and obey all applicable intellectual property law.
- **Honest, lawful conduct.** The plugin and its developers must not do anything illegal, dishonest, or abusive. No fake or incentivized reviews, no sockpuppet or throwaway accounts to inflate ratings or reviews, no shipping another person's GPL work as your own without credit, and no harassment of users, reviewers, or other developers.

The Plugin Directory team can enforce these guidelines: it can remove or disable a plugin that breaks them, and it can grant occasional exceptions at its discretion. The team can also update the guidelines at any time, so check the current published version before each release.
