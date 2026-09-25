# Scoring rules

Apply these rules as written. Every label needs the URLs or path:line that justify it. The
hosted search may not show suggested searches or "People also ask"; when it does, cite them
as extra evidence, but no label depends on them.

A working free tool is a page that gives a visitor a usable result without signup or
payment: an interactive checker, calculator, generator or converter, or a template that
downloads without an account. Articles, guides and listicles are not tools.
Count only tools that answer what the phrase asks for; a tool for a different intent that
happens to rank is not evidence. Several pages from one site count as one tool. A close
equivalent is a tool that gives the same result for the same input, including a template
embedded in a guide. A tool page is any ranking page that offers to do the job, working or
not. A page you could not open or use counts as a tool page but never as a working tool.

## Demand label (from observed search results only)

- strong: two to five tool pages rank for the phrase, you opened at least two of them, and
  at least one you opened is visibly weak: gated before any result, paywalled, ad-heavy, broken, outdated, missing an
  input the phrase needs, or a static table where the visitor expects a calculation.
- A saturated phrase, where six or more polished working free tools rank, is weak however
  weak the others are, and its gap scores at most 1. When only articles rank, with no tool
  pages at all, demand is at most weak and gap at most 1.
- weak: the phrase is clearly searched (articles, guides, templates, forum questions or a
  single tool rank for it) but the strong conditions do not hold, including when the
  existing tools are all good.
- none: the results do not match what the phrase asks for, or nothing relevant ranks.

Never convert a label into a number of searches or visitors.

## Winnability label

Judge from what is visible on the first page you saw: recognisable brands, aggregators and
long-established reference sites versus small companies, individual developers and niche
sites. Say which results you judged and why.

- open: at least one small or niche site ranks with a page aimed at the phrase, whether or
  not it is a tool.
- crowded: every result aimed at the phrase comes from a large, long-established brand or
  aggregator.

## Build effort

Build effort is the work to ship one public page, not whether code is reused. Reusing the
repository's own logic lowers effort; it is not required.

- low: a static or browser-only page a developer could ship in a few days, whether it
  wraps existing code or is written fresh.
- medium: needs a small server endpoint, separating logic from private data or framework
  code, or up to about two weeks of work.
- high: needs a new service, data pipeline or anything larger.

Code under the company's own commercial or enterprise licence is still the company's to
reuse; note the licence when you cite it.

## Vetoes (any one rejects the candidate)

1. already-shipped: the company already offers this tool, or a close equivalent, publicly
   (check the product site's tools, free or resources pages and the repository's marketing
   pages). An extension of a shipped tool counts too; name the improvement in the report
   instead. A page that only shows examples, with no input or download, is not a tool.
2. customer-data: the tool needs a visitor's or customer's account, data or usage history.
   A file the visitor chooses to process in their own browser does not count.
3. visitor-credentials: the tool asks visitors for secrets or API keys, or would expose a
   company secret in the browser. A server-side call to the company's own public
   infrastructure is allowed; count its cost in upkeep.
4. sensitive-logic: publishing the logic would expose proprietary pricing, fraud, ranking,
   security or compliance rules the company would not want copied or gamed.
5. core-value: the free tool would do the job customers currently pay for.
6. no-demand: demand label none.
7. crowded: winnability label crowded.
8. no-path: there is no plausible step from using the tool to needing the product. A tool
   whose users are not the product's buyers is traffic, not growth.
9. excluded: matches the exclude input.

## Rubric for survivors (0 to 2 each; maximum 10)

- path: 2 when the tool's result leads straight into the product's job (the visitor's next
  step needs the product, or the tool is used while choosing a product like this one) and
  a free incumbent the visitor already uses does not meet that next step just as well; 1
  when the link is only topical or the incumbent meets it; 0 otherwise.
- gap: 2 when an observed, specific weakness of the ranking tools is fixed, 1 when the gap
  is only "cleaner" or "free without signup", 0 when the existing tools already do it well.
- demand: strong 2, weak 1.
- build: low 2, medium 1, high 0.
- upkeep: 2 for a static or browser-only page with no per-use cost and no data to keep
  current; 1 for a small server, or for a page whose accuracy depends on third-party data
  maintained by hand, such as competitor prices; 0 when each use costs paid API calls or
  invites abuse.

A comparison the company publishes about its own competitors is read as biased unless it
shows its sources, dates and method on the page; make that part of the spec.

## Choosing the pick

A survivor can be the pick only if it scores at least 6, with path 2 and gap at least 1.
Among eligible survivors choose the highest total; break ties by higher path, then higher
gap, then a candidate built on the repository's own cited code over one written fresh, then
higher demand, then lower build effort. Order runners-up by the same rules. If no survivor is eligible, the verdict is
"No tool worth building". Every other survivor is a runner-up: the best two get a paragraph,
the rest one line each. A survivor that scores at least 6 but misses the path or gap
condition is a runner-up, not rejected.
