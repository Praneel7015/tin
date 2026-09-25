# Report layout

Write Markdown in this order. Keep the part above `## Shelf check` under 6,000 characters: it is
what the founder reads. Short sentences. Name the marketplace, then the fact. Dates are UTC.

````markdown
# Partner marketplace listings: <product>

Status: complete | incomplete | diagnostic
Checked: <YYYY-MM-DD> · Code map: <verified date and commit from its heading> · Budget: <n>/40 web actions
Context: <Feature map, growth plan, writing style guide: "read" or "none found" for each>

<One sentence: the decision. "Submit to GitHub Marketplace this week; fix two pages before
Slack." or "Nothing new to submit this week: GitHub from <date> still waits on you." or
"Nothing to submit this week: <the one change that unblocks the best row>.">

## Submit this week

### 1. <Marketplace> · score <n> · <ready | fix first | confirm>
Why here: <the integration, its Code map evidence, and who is already listed there>.
Before you submit:
- <each fix or confirmation, with the page or rule it clears>
Submit at: <URL of the marketplace's submission or developer page>
Review: <stated review time>

| Field | Copy | Chars / limit |
|---|---|---|
| <field> | <copy> | <n> / <limit or "no stated limit"> |

Screenshots to take:
- <screen, state, size>

(repeat for each pick)

## Fix first
- <marketplace>: <gate> → <fix>. Unblocks <what>.

## Since last run
- Went live: <ids or "none">
- Waiting on you: <id (recommended <picked_on>, packet in <picked_in>)> or "none"
- New in the Code map: <ids or "none">
(or "First run: no earlier report." or "Continuity unavailable: <why>.")

## Shelf check

| Integration | Shape | Marketplace | You | Similar tools listed | Readiness | Score |
|---|---|---|---|---|---|---|
| <service> | <shape> | <id> | listed / absent / unknown | <n>: <names> | <state> | <n or reason> |

## Not a storefront
- <service> — <shape>: <why, in a few words> · <path:line>

## No marketplace in the reference
- <service> — <what it does> · <path:line>

## Evidence
- <marketplace> presence: <query or URL> → <result> (<date>)
- <marketplace> similar tools: <URL> …
- <marketplace> gate "<rule>": <page or path:line> → pass / fail / unknown
- <marketplace> rules recheck: <source URL> → unchanged / <difference>

```tin-listings-state
{"version": 1, "checked": "<YYYY-MM-DD>", "rows": {"<id>": {"presence": "absent", "picked_runs": 1, "picked_on": "<YYYY-MM-DD>", "picked_in": "<this report's path>"}}}
```
````

The diagnostic report, when the Code map is missing, is only:

```markdown
# Partner marketplace listings

Status: diagnostic

No `### Code map` with an `**Integrations**` block was found in `wiki/INDEX.md`. Run
"Map the product from its code" (product.code_map) first, then run this again.
```

Never leave a section out: write `- none` when it is empty. Never state a presence, a gate result
or a competitor listing without its URL or path under Evidence.
