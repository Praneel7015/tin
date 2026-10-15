# Connection requests

`social.linkedin_requests` (#450) sends the LinkedIn connection requests a member approved, one
at a time, from their own saved session, then reads who accepted. It follows
[People who engaged with your LinkedIn posts](linkedin-engagers.md), whose people it proposes.
Boards: Paper "Warm reach · connection requests", INVITE-A to INVITE-C.

## Proposed

At the end of an engagers run, `linkedin_requests.propose` puts everyone newly eligible into
the starter's open batch (one open batch per member and project). Someone is eligible when:

- they reacted to or commented on the starter's own posts (events from runs the starter began);
- their ICP fit is 0.6 or more, whoever set it;
- they aren't connected or already invited (`linkedin_relationship` is `none`);
- they aren't marked a customer;
- the starter never had them in a batch before, decided or not.

The batch waits in Decisions under "Connection requests", for that member only: another
member's LinkedIn would send it, so nobody else sees or decides it. Over MCP,
`list_open_decisions` returns it as `connection_requests`.

## Approved

Approving (`POST /api/projects/{project_id}/linkedin-requests/batches/{id}/approve`, or
`approve_connection_requests`) queues the people the member ticked and declines the rest;
discarding declines everyone. Nobody declined is proposed again. The same `request_id`
repeats the same decision. Approving needs sending to be on, and starts the batch's
`social.linkedin_requests` run with the start key `linkedin-requests:<batch>`; nothing else
can start it. Nothing is sent at the moment of approval. If the run can't start, the batch goes
back to Decisions as it was and the member reads why.

## Sent, one at a time

Sending is per member and project, off until the member turns it on on the LinkedIn card by
ticking the consent box (`PUT …/linkedin-requests/sending` with `consent_version` 1). It needs
the member's cloud reading, whose saved session it sends with; reading in this browser only
keeps the switch off. MCP can't turn it on. The card says plainly that LinkedIn's terms don't allow automated requests
and that pacing lowers the risk to the account without removing it.

The run asks `linkedin_requests_next` what to do and follows: send, wait, read who accepted,
or finish. Every decision about time is made from Postgres, so history holds only request IDs,
waits and outcomes. A request may go when, for the member across all their projects:

- it's a weekday inside the window (09:00–17:00 by default) in the founder's time zone: the one
  Start here recorded, else the newest saved schedule's, as the organic system reads it;
- at least 15 minutes have passed since their last request, plus a wait of up to 25 minutes
  that each request draws once from its ID;
- they're under the daily and weekly caps (15 and 60 by default, half in their first week of
  sending; the member can change them within 1–25 and 1–100);
- sending isn't paused.

`linkedin_requests_send` reserves the turn under a per-member lock, then sends in the LinkedIn
sandbox under an effect receipt (`linkedin_request_v1`). The sandbox's `linkedin_invite` kind
checks `/me`, reads the person's top card, and posts the request (no note) only when the card
shows neither a connection nor an invitation. Outcomes:

| Outcome | Request | Sending |
|---|---|---|
| sent | `sent`; the person reads "Invited", with an `invited` event | goes on |
| already connected or invited | `connected` / `invited`, nothing sent | goes on |
| LinkedIn didn't show the relationship | `unknown_person`, nothing sent | goes on |
| refused by LinkedIn | `refused` | paused until the member resumes |
| LinkedIn's weekly limit | queued again | held until Monday's window |
| a checkpoint, signed out, blocked, slow down | queued again | paused until the member resumes |
| may have gone out (no answer, a sandbox that started and stopped) | `uncertain`, never sent again | goes on |

Approvals not sent within 14 days lapse.

## Who accepted

About a day after the newest request, and then daily, `linkedin_requests_check` reads the
relationship of up to 20 waiting people (`linkedin_relationships`): connected becomes
`accepted` (with an `accepted` event), still invited stays, and neither becomes `not_pending`
(declined or withdrawn) or, for an uncertain one, `not_sent`. Requests stop being read three
weeks after they were sent. Withdrawing old requests isn't built yet: no LinkedIn endpoint for
it has been verified.

When nothing is queued or waiting, the run writes `people/connection-requests.md` (who, and
what happened) and finishes with a one-line summary. A run that fails lapses what it had
queued.

## Where it shows

- **Decisions:** the batch's card lists each person with their headline, ICP, fit and what they
  engaged with; unticking skips someone. It says when the first and last would go.
- **LinkedIn card:** the Sending row (switch, consent, limits, the paused state with Resume) and
  This week (sent, accepted, queued, pending, next send). A held sending makes the card need
  you.
- **People:** "Invited oct 16" in the LinkedIn column, an Invited segment once someone is
  invited, and "Connection request sent" / "Accepted your connection request" on the timeline.

The sandbox image needs the new runner kinds: build a new `tin-linkedin-*` alias from
`sandbox/linkedin/Dockerfile` and point `TIN_LITE_LINKEDIN_TEMPLATE` at it, staging first.
Deleting a project removes its sending settings, batches and requests.
