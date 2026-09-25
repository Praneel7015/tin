# Product analytics brief

`product.analytics_brief` reads one connected PostHog project and writes a standing
brief: activation, key-event trends, traffic, error signals and one useful breakdown.
It reports findings and their evidence, without recommendations or changes to the
customer's product. It does not inspect session replays or fix instrumentation.

## Set it up once

Connect PostHog in the project's Integrations: OAuth with read scopes only, then
choose the one PostHog project the brief reads (see
[Stripe and PostHog connections](stripe-and-posthog-connections.md)). The package
binds `analytics.posthog` with `query.read` and `definitions.read`; tokens stay in
Tin, never in workflow files, inputs or the sandbox. The brief has no project input:
it always reads the project selected on the connection, so switching that project
changes what the next brief reads (its schema check then reports the change).

Save the workflow with the reporting window and any known funnel or exclusions. Leave the funnel empty to have the procedure propose one
from available event evidence and project context. Discovery reads up to 200 event types
ranked by recent volume and discloses the total catalog size. Selected metrics query their
complete event/window populations; events outside the discovery list are not assumed absent.
The report states what it chose
and why; edit the saved inputs to correct it. Missing semantics are a limitation,
not permission to invent an activation event or treat an identifier as a human.

Choose manual, daily or weekly execution through the ordinary saved-workflow form.
Existing schedule authorization and billing rules apply. Results arrive in Tin's
Files and Activity, with a separate `reports/analytics/<run_id>.md` for each run.
This package does not add email or Slack delivery.

Use a separate Tin project for a separate PostHog project. Website visitors and
product accounts are different populations; this workflow does not join them.
A project without pageviews can still produce a useful product brief, with traffic
explicitly unavailable. When pageviews exist, the procedure checks PostHog's documented web
properties through the same bounded queries. A missing session key on a server-side product
event can prevent a same-session funnel without preventing independent website traffic analysis.

## What is checked

The bounded procedure chooses and explains the analysis. Declared Python/SQL
resources own query construction, ordered counts, rates and statistical checks.
Queries return aggregates, with raw identities kept inside PostHog. Source data
and previous reports are evidence, never instructions. Read-only access comes from
the OAuth scopes. Tin's gateway checks each query's shape (one SELECT of at most
8000 bytes, final LIMIT of at most 1000, no OFFSET or UNION) but not its analytic
semantics; the procedure instructions are reviewed behavior, not a SQL sandbox.
Each run uses at most eight calls: seven aggregate queries and one property-definition
read that checks the chosen identity and dimension properties are strings.

Every table identifies its window, population, exclusions and unit. Queries use
explicit UTC boundaries. Missing keys, late instrumentation, zero denominators,
small samples and incomplete provider responses stay visible. First observed data
does not establish when an event became reliable or what its firing site means.
A failed required query makes the brief incomplete; an honest diagnostic is not
a passing ordinary qualification case.

A screened breakdown is descriptive evidence, not proof of causation. The report
names the test and its multiple-comparison correction. No supported split is a
valid outcome; the procedure must not keep searching until it finds significance.

## Qualification and publication

The package and `workflow_evals/product.analytics_brief/qualification.json` use the
same creator/qualifier contract as external contributions. Static checks establish
shape. Offline tests exercise calculations, query construction and bad responses.
They do not establish provider compatibility or model quality.

Live qualification separately checks the exact generated SQL against controlled
provider cases and reviews real reports against retained query results. Package
and case digests identify the evaluated version. A private on-demand copy is a
different manifest from the scheduled public package; do not describe its run as
exact public-package acceptance. Public schedule execution needs its own test
deployment or post-merge acceptance.

Model cost is unmeasured until priced runs exist for that package and case. A
configured ceiling is not an expected price. The existing usage receipts and
ledger charge verified actual model usage; connected PostHog spending is separate
and is not asserted to be free. Event/schema complexity, discovery, response sizes
and interpretation affect agent cost.

Maintainers review source, useful results, safety and measured costs before
publication. Explicit `PUBLIC_WORKFLOWS` registration is reviewed in the PR;
deployment/catalog sync is the publication step. No creator or evaluator publishes
automatically, and existing private runs and saved versions stay pinned.
