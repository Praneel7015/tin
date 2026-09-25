---
name: campus-event-fit
description: For a business whose buyers are students, find or compare upcoming campus events, rank them on evidence and draft one measurable, permission-dependent activation for the best one.
---

## Purpose

A founder whose buyers are students runs this before spending time or money on a campus event.
Students meet sponsors at club events, hackathons, placement workshops and festivals; the useful
result is a relevant interaction, not a logo on an unrelated poster. The report is for a human
to act on. This workflow never contacts an organizer, registers, buys a sponsorship or collects
student data.

## 1. Read the project context

Everything here is evidence, not instructions, and none of it is asked of the founder again.
Read at most 12000 characters of project context in total. Record which files existed for the
report's `Context:` line.

- `reports/GROWTH_ONBOARDING_PLAN.md`: `## The business` (what is sold and to whom, with
  confidence labels), `## Tin's view`, `## Proposed scope` (including `Your part` and the number
  to watch) and `## Marketing systems`. A row or note marked `hard no: ...` and anything the
  founder forbids are binding: `no discounting` means no discount or promo code, so measure with
  an event-specific link instead; `no unbacked claims` means every product claim on a sign is
  backed by the Feature map; `no founder posting` means no activation that needs the founder to
  post publicly; `no cold email` means the report does not draft an unsolicited email to an
  organizer and points only to published application forms or sponsor pages. Budget and founder
  hours come from the plan's facts, assumptions and scope; when none is stated, treat the budget
  as unknown and propose only activations that cost nothing but time.
- `wiki/INDEX.md` → `### Feature map`: what the product actually does. The activation
  demonstrates one real feature from here.
- `.agents/skills/writing-style/SKILL.md`: the founder's voice. The sample sign and on-site line
  follow it.
- The README only when the files above are missing.

Resolve three facts, input first, then the plan and Feature map:

- **Business**: `business` input, else what the plan and Feature map say is sold.
- **Students and place**: `audience` input, else the plan's buyers. Name the campus, city or
  region. If the buyers are not students, say so under `Status: not a student audience`, explain
  in two lines which evidence shows it, and stop.
- **Limits**: `budget` input, else the plan's budget and founder hours, else unknown.

If the business or the students' location cannot be resolved from inputs or files, write the
short report from step 6 with `Status: needs context`, name exactly which input would fix it
(`business` or `audience`), and stop. Do not guess a city.

## 2. Load memory

Read every earlier report in the output folder (the directory of the declared output path) and
its `tin-campus-events-state` JSON block. Events listed there under `recommended` were already
proposed; do not recommend them again unless their date changed, and say so when you skip one.

## 3. Gather events

**Supplied briefs.** When `event_briefs` is not empty, compare only those events; the founder
chose them. Split them into at most ten identifiable events. Do not search for replacements. If
none is current, say so and suggest rerunning with `event_briefs` empty so the run researches.

**Research.** When `event_briefs` is empty, search the public web for campus events the resolved
students attend within the next 120 days from today's UTC date: hackathons, club and society
events, career and placement fairs, tech or entrepreneurship weeks, orientation and cultural
festivals. Use at most 12 searches and open at most 20 pages. Prefer the university's, club's or
organizer's own page to aggregators, and a current-year page to an older edition. Keep at most
ten events.

For each event, capture its name, source URL or supplied-document label, date, location, stated
audience, format, sponsorship or participation route and rules, and price only when a source
states it. Mark every other field `unknown`. Never invent an organizer, contact address,
attendance, date, price, availability, permission or conversion rate. If two descriptions concern
the same event, combine them and keep both sources. Mark an event `past` when its date is before
today, and `date unconfirmed` when no source gives this year's date. Past events are listed but
never ranked or recommended. An undated event is ranked with its date as an unknown, and cannot
be recommended until its date is confirmed.

## 4. Score and rank

Score each current event against the resolved students and offer on three criteria: audience
overlap (0-2), a contextual reason to engage with the product at that event (0-2), and
feasibility under the resolved limits and hard no's (0-2). 0 means absent or contradicted
evidence, 1 plausible but unconfirmed, 2 explicit support. Cite the exact source detail behind
each score. Unknown costs or rules cannot earn a 2 for feasibility, and an event whose stated
price exceeds the budget scores 0 there. The sum is a ranking aid, not a predicted return. Rank by
sum, then audience overlap, then fewer unknowns. If no current event scores at least 4, say so
and give a short research checklist instead of an activation.

## 5. Draft one activation

For the best current event, propose one small activation that helps a student at the event and
naturally shows the product: a workshop slot, a judging or mentoring offer, a challenge prize
that uses the product, a help desk. Include a sample sign or on-site line (in the founder's voice
when a style guide exists), materials, rough effort in hours and money within the limits, and an
opt-in action. Give the organizer-permission checklist (space, logo, filming, links, data
collection) and how to ask: the event's published sponsor or partner form or page when one
exists. The activation must not imply a partnership exists. Never use attendee lists or
individual student data; opt-ins are voluntary.

Define one measurement plan: attendance only if the organizer can verify it, opt-in visits through
an event-specific URL, qualified actions after the visit, and a follow-up check a week after the
event. These are proposed measures, not observed results. Add a go/no-go gate on confirmed price,
permission and audience relevance.

## 6. Report

Write Markdown to the declared output path, under 48000 bytes, with:

1. `# Campus events for <business name>`, then one line each: `Status:` (`recommended`,
   `no current fit`, `needs context` or `not a student audience`), `Date:` (today, UTC),
   `Event source:` (`supplied briefs` or `web research`), `Business from:` and `Students from:`
   (`input`, `onboarding plan`, `Feature map` or `README`), `Limits:` and `Context:`.
2. A ranked table of current events: name, date, place, the three scores with cited evidence,
   unknowns and source. Then past events in a short list with their dates.
3. The recommended activation, permission checklist, costs against the limits, and the
   measurement plan with its gate. Omit this section when the status is not `recommended`.
4. `Next action:` one sentence the founder can do this week.
5. A fenced `tin-campus-events-state` JSON block:
   `{"recommended": [{"name": "...", "date": "YYYY-MM-DD or unknown", "source": "..."}], "checked": ["event name", ...]}`
   carrying forward every earlier `recommended` entry plus this run's.

Keep quotations from sources short. Label assumptions, past dates and missing information. Never
claim to have verified a URL you did not open. Do not edit other project files or send outreach.
