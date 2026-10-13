# LinkedIn posting

Tin posts to LinkedIn through Zernio (zernio.com), on Tin's own Zernio account. Zernio
holds LinkedIn's app approvals for member and organization posting, so Tin needs no
LinkedIn app review. This page covers the connection. Publishing reuses X's preview and
confirmation path and lands separately.

## Connect

The **LinkedIn posting** card (`social.linkedin`) is separate from the **LinkedIn** card
(`network.linkedin`), which collects connections through the browser extension.

1. **Connect** makes the project's Zernio profile, or finds it again. There is one profile
   per project, named `tin:<project id>`, with the project ID as its `externalId`.
2. The founder signs in to LinkedIn through Zernio's hosted connect and picks where Tin may
   post: themselves, the pages they administer, or both. Each pick is its own Zernio
   account in the project's profile. The consent covers posting, analytics and comments,
   so later reads need no second sign-in.
3. Zernio returns to `/integrations/callback/linkedin`, carrying Tin's attempt state. Tin
   checks the signed-in member and the attempt, then reads the accounts from the project's
   profile. It ignores any account IDs in the callback's query.

The connection row keeps the profile ID and each account's Zernio ID, LinkedIn URN, kind
and name. Tin stores no LinkedIn credential, because Zernio holds the tokens and refreshes
them. **Check again** reads the accounts again; a profile with no active account needs
reconnecting. **Add accounts** runs the same connect, and Zernio refreshes accounts it
already has.

## Boundaries

- `TIN_LITE_ZERNIO_API_KEY` stays on the switchboard. It never reaches a sandbox, package,
  project file, log or Temporal history.
- One key acts on every project's LinkedIn. The server picks the profile and account from
  the project, never from a request.
- One LinkedIn sign-in can post as every page the member administers. Tin posts only as
  the accounts connected into the project's profile, by Zernio account ID, and never names
  an organization of its own.
- Zernio bills Tin for each connected account each month. The card is shown only to the
  projects in `TIN_LITE_LINKEDIN_POSTING_PROJECTS`.
- **Disconnect** removes the project's accounts and then its profile from Zernio, and so
  does deleting the project. A failure there is logged; the local disconnection stands.

## Staging

Staging and production share Tin's Zernio account, so staging never creates a profile or
connected account of its own. `TIN_LITE_ZERNIO_PROFILE_MAP` (`<project id>=<profile id>`,
comma-separated) points a staging project at an existing profile. Connect then attaches
that profile's accounts without a LinkedIn sign-in, and disconnect never changes the
profile in Zernio. Without a mapping, staging refuses to connect.

## Setup

| Setting | Value |
|---|---|
| `TIN_LITE_ZERNIO_API_KEY` | Tin's Zernio API key |
| `TIN_LITE_LINKEDIN_POSTING_PROJECTS` | Comma-separated project UUIDs that see the card |
| `TIN_LITE_ZERNIO_PROFILE_MAP` | Optional; required on staging |

Apply `064_linkedin_posting.sql`, which adds `social.linkedin` to the integration tables'
provider checks. It adds no tables.

## Checked against Zernio

Before building, a connection on Tin's own company page confirmed:
- hosted connect and the page picker;
- presigned media upload;
- `Idempotency-Key` replay;
- the 24-hour duplicate-content refusal;
- deleting a scheduled post;
- reading page comments.

A member's own posts are not readable through Zernio, so reading the founder's own posts
stays with the extension. Fixture tests use a synthetic Zernio
(`tests/test_linkedin_posting.py`).
