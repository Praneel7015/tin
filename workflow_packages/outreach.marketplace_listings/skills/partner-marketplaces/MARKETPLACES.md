# Marketplace reference

This is the closed list of storefronts the skill may recommend. Each entry names what in the code
makes a product eligible, the rules a listing must pass, the form fields to fill and where the rules
come from. Values were read from the official pages on 2026-09-23. Rules change: before filling
a packet for a pick, reopen its `Rules source` once and follow the live page if it disagrees,
noting the difference under Evidence.

Use the ids exactly as written; SCORING.md and the report refer to them. Do not map an integration
to a marketplace that is not in this file. To add a marketplace, add an entry with an official
rules source and a checked date, in the same shape.

Fields in each entry:

- **Storefront for**: the integration shape and code signals that make the product listable here.
  Using the partner as your own vendor (billing, email delivery, hosting, models) never qualifies.
- **Find a listing**: the domain to search and the marketplace's own search, when it works
  without signing in.
- **Hard gates**: rules that decide eligibility. `size` is `small` when a founder can fix it in a
  day (a page, a link, a form) and `large` when it needs a build, an audit, users or weeks.
- **Form**: fields the submission asks for, with limits where the source states them. Where the
  source gives no limit, write copy that would fit a short field and say "no stated limit".
- **Review**: the stated review time, used as the tie-breaker.
- **Effort**: 1 = listing only, 2 = listing plus small setup, 3 = a build or third-party review.

---

## slack — Slack Marketplace

- **Storefront for**: `user_authorized`. Slack workspaces install the product through Slack OAuth v2
  ("Add to Slack", `oauth.v2.access`, `@slack/bolt`, `slack_sdk` with a distributed app). A
  product that only posts to a customer-supplied incoming webhook is `outbound_only`.
- **Find a listing**: `slack.com/marketplace`; search `site:slack.com/marketplace "<product>"`.
- **Hard gates**:
  - installed on 10 or more active workspaces, active in the past 28 days (large; founder confirms)
  - publicly available and installable, with existing customers (large)
  - not a coded workflow, not a financial or crypto transaction app (large)
  - install, setup, use and uninstall tested on non-development workspaces (small)
- **Form**: app name, short description, long description, icon, screenshots, support and
  privacy links. The review guide states no character limits.
- **Review**: preliminary up to 10 business days; functional review up to 10 weeks for a new app.
- **Effort**: 2
- **Rules source**: https://docs.slack.dev/slack-marketplace/slack-marketplace-review-guide

## github — GitHub Marketplace

- **Storefront for**: `user_authorized`. Customers install a GitHub App on their repositories or
  organisations (app ID and private key, `installation` webhooks, `@octokit/app`, PyGithub app
  auth), or authorise a GitHub OAuth app.
- **Find a listing**: `github.com/marketplace?query=<product>`.
- **Hard gates**:
  - valid privacy policy link (small)
  - working support link or email and valid publisher contact (small)
  - a stated pricing plan; free plans are allowed (small)
  - publicly available; no invite-only or preview access (large)
  - Marketplace API webhook events for plan changes and cancellations, free listings too
    (large: needs code in the app)
  - paid plans only: 100 GitHub App installations or 200 OAuth app users, and a verified
    publisher organisation (large)
- **Form**: listing name at most 255 characters; very short description 40 to 80 characters, no
  ending punctuation, not repeating the name; introductory description 150 to 250 characters,
  starting with the app name; detailed description at most 1,000 characters as 3 to 5 sections
  with level-three headings; primary and optional secondary category; logo at least 200x200 with
  no text; feature card 965x482; up to 5 screenshots at least 1200px wide; customer support URL,
  privacy policy URL, and a setup URL for GitHub Apps; pricing plan.
- **Review**: GitHub reviews every new listing; no time stated.
- **Effort**: 1 for a free listing, 3 for paid.
- **Rules source**: https://docs.github.com/en/apps/github-marketplace/creating-apps-for-github-marketplace/requirements-for-listing-an-app and
  https://docs.github.com/en/apps/github-marketplace/listing-an-app-on-github-marketplace/writing-a-listing-description-for-your-app

## google_workspace — Google Workspace Marketplace

- **Storefront for**: `user_authorized`. Users sign in with Google and grant the product scopes
  on Gmail, Calendar, Drive, Docs or Sheets (`googleapis.com/auth/gmail.*`, `calendar.*`,
  `drive.*`).
- **Find a listing**: `workspace.google.com/marketplace/search/<product>`.
- **Hard gates**:
  - OAuth app verification for sensitive scopes, such as reading Calendar events (large)
  - restricted scopes, such as reading Gmail messages, need an independent security assessment
    renewed every year (large)
  - Marketplace app review against the listing and design guidelines (small)
  - privacy policy and terms of service on the product's domain (small)
- **Form**: app name, short and detailed description, icons, screenshots, support, privacy and
  terms URLs, OAuth scopes. Limits are shown in the Marketplace SDK form.
- **Review**: Marketplace review after OAuth verification; OAuth verification time varies.
- **Effort**: 3 when restricted or sensitive scopes are requested, otherwise 2.
- **Rules source**: https://developers.google.com/workspace/marketplace/about-app-review and
  https://developers.google.com/identity/protocols/oauth2/production-readiness/restricted-scope-verification

## zapier — Zapier App Directory

- **Storefront for**: `user_authorized` in the other direction: the product has its own public
  API that its users authenticate to with API keys or OAuth, so Zapier can call it. The Code map
  shows public API routes and user-issued keys.
- **Find a listing**: `zapier.com/apps/<product-slug>/integrations`; search
  `site:zapier.com/apps "<product>"`.
- **Hard gates**:
  - you own the API or are contracted by its owner (large)
  - the product is fully launched to the public (large)
  - an admin on the Zapier team has an email on the product's domain (small)
  - a non-expiring test account for integration-testing@zapier.com (small)
  - production endpoints over HTTPS; every trigger and action has a tested Zap run (large: needs
    the integration built on Zapier's platform)
  - listed as beta for 90 days before public, unless an embed signup ends it early (time)
- **Form**: app name matching the brand exactly, description in the form "X is a ...", no links,
  homepage URL of the marketing site (not the login page), logo, category.
- **Review**: Zapier replies within one week of submission.
- **Effort**: 3
- **Rules source**: https://docs.zapier.com/platform/publish/integration-publishing-requirements

## hubspot — HubSpot App Marketplace

- **Storefront for**: `user_authorized`. A public HubSpot app with OAuth (`api.hubapi.com`,
  `oauth/v1/token`).
- **Find a listing**: `ecosystem.hubspot.com/marketplace/apps`; search
  `site:ecosystem.hubspot.com "<product>"`.
- **Hard gates**:
  - at least 3 active unique installs from unaffiliated production accounts in the past 30 days
    (large; founder confirms)
  - OAuth is the only authorisation method (large)
  - public setup documentation specific to the HubSpot integration (small)
  - terms of service, privacy policy and a support contact (small)
  - pricing in the listing matches the website (small)
- **Form**: integration-specific description, install button URL, setup docs URL, shared data
  table matching the requested scopes, pricing, support. Every URL field is at most 250 characters.
- **Review**: first review within 10 business days; the feedback process at most 60 days.
- **Effort**: 2
- **Rules source**: https://developers.hubspot.com/docs/api/app-marketplace-listing-requirements

## shopify — Shopify App Store

- **Storefront for**: `user_authorized`. Merchants install a Shopify app (`@shopify/shopify-api`,
  App Bridge, Admin API with OAuth).
- **Find a listing**: `apps.shopify.com/search?q=<product>`.
- **Hard gates**:
  - charges go through the Shopify Billing API or managed pricing (large)
  - OAuth redirects through App Bridge; documented Shopify APIs only (large)
  - privacy policy (small)
  - screencast and test credentials for review (small)
- **Form**: app name at most 30 characters, introduction at most 100, details at most 500,
  feature lines about 80 each, 3 to 6 desktop screenshots at 1600x900.
- **Review**: no time stated on the checklist.
- **Effort**: 3
- **Rules source**: https://shopify.dev/docs/apps/launch/app-requirements-checklist

## notion — Notion Marketplace (connections)

- **Storefront for**: `user_authorized`. A public Notion connection with OAuth
  (`api.notion.com/v1/oauth/token`) whose installation scope is "Any workspace".
- **Find a listing**: `notion.com/integrations`; search `site:notion.com/integrations "<product>"`.
- **Hard gates**:
  - public connection with installation scope "Any workspace"; internal and selected-workspace
    connections cannot be listed, and the scope cannot be changed later (large)
  - brand and trademark use that Notion accepts (small)
- **Form**: listing drafted in the Marketplace dashboard under Listings, then submitted.
- **Review**: reply within 5 to 10 business days.
- **Effort**: 2
- **Rules source**: https://developers.notion.com/guides/get-started/marketplace-listing

## stripe — Stripe App Marketplace

- **Storefront for**: `user_authorized`. A Stripe App that Stripe users install into their own
  account (`stripe-app.json`, Stripe Apps UI extensions, or a backend app installed with OAuth).
  Using Stripe to bill your own customers is `vendor_side` and never qualifies.
- **Find a listing**: `marketplace.stripe.com`; search `site:marketplace.stripe.com "<product>"`.
- **Hard gates**:
  - the app is built on Stripe Apps (large)
  - activated Stripe account; one app per account; English listing (small)
  - business not on Stripe's prohibited and restricted list (large)
  - a test plan and credentials when the app needs an account (small)
- **Form**: overview, features, pricing, support, resource links.
- **Review**: automated scans, live testing and human review; no time stated.
- **Effort**: 3
- **Rules source**: https://docs.stripe.com/stripe-apps/publish-app and
  https://docs.stripe.com/stripe-apps/review-requirements

## vercel — Vercel Marketplace

- **Storefront for**: `user_authorized`. A Vercel integration: native (Marketplace API and an
  integration server) or a connectable account (redirect URL and OAuth), which Vercel users add to
  their projects.
- **Find a listing**: `vercel.com/marketplace`; search `site:vercel.com/marketplace "<product>"`.
- **Hard gates**:
  - the integration passes Vercel's approval checklist (large)
  - the Create Product form is complete for at least one product, for native integrations (small)
  - submission by email to integrations@vercel.com (small)
- **Form**: product details in the integration console.
- **Review**: on request; no time stated.
- **Effort**: 3
- **Rules source**: https://vercel.com/docs/integrations/create-integration/submit-integration and
  https://vercel.com/docs/integrations/create-integration/approval-checklist

## chrome — Chrome Web Store

- **Storefront for**: `distributed_artifact`. The product ships a browser extension (a
  `manifest.json` with `manifest_version`).
- **Find a listing**: `chromewebstore.google.com/search/<product>`.
- **Hard gates**:
  - developer registration and a one-time fee (small)
  - a new publisher can have at most two published items (small)
  - privacy tab: purpose and data handling declared (small)
- **Form**: name, summary, detailed description starting with what the item does, category,
  icon 128x128, 1 to 5 screenshots at 1280x800, small promo tile 440x280.
- **Review**: after approval the submission can be published within 30 days.
- **Effort**: 1
- **Rules source**: https://developer.chrome.com/docs/webstore/publish and
  https://developer.chrome.com/docs/webstore/cws-dashboard-listing

## mcp_registry — Official MCP Registry

- **Storefront for**: `distributed_artifact`. The product ships an MCP server (`server.json`,
  `@modelcontextprotocol/sdk`, a Python `mcp` server, or a remote MCP endpoint).
- **Find a listing**: `registry.modelcontextprotocol.io/v0/servers?search=<product>` (JSON).
- **Hard gates**:
  - namespace ownership: `io.github.<user>/` through GitHub sign-in, or a domain namespace through
    DNS verification (small)
  - the server's package is published upstream (npm, PyPI, NuGet) with a matching marker, or it
    is a remote server with a URL (small)
- **Form**: `server.json` metadata, published with the `mcp-publisher` CLI.
- **Review**: none documented; publication is automated once validation passes.
- **Effort**: 1
- **Rules source**: https://github.com/modelcontextprotocol/registry/blob/main/docs/modelcontextprotocol-io/quickstart.mdx
