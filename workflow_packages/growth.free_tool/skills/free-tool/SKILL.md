---
name: free-tool
description: Pick one free public tool a small software company should build for search traffic, grounded in observed search results and cheap to build from its own repository.
---

# Free tool procedure

Engineering as marketing: a small free tool that answers a question buyers already search
for (a grader, checker, calculator, generator, validator, converter or template) can earn
traffic and trials for years. HubSpot's Website Grader and CoSchedule's Headline Analyzer
were designed around existing buyer searches, not dug out of a codebase. So this procedure
runs demand first, favours tools used by people choosing or about to need the product, and
uses the repository to lower the build effort. Read SCORING.md and REPORT.md before you
start and apply them unchanged.

Budget: at most 12 candidate phrases (close variants you search together count as one), at
most 24 web searches, and at most 16 page fetches (product pages and result pages). Stop
reading code once each surviving candidate has its evidence. Leave time to write the report;
a finished report that names what it did not check beats an unfinished one.

## 1. Learn the buyer and what already exists

Read product_url, then the repository README, package manifests and route or command names.
If the product page renders empty, use search snippets from the product's own domain and the
repository's marketing pages instead, and say so. Write down, in one line each: what the
product does, who pays for it, and the recurring job that buyer does before or while
choosing a product like this one. If focus is set, favour that buyer or area.

List the free tools the company already offers: look for tools, free, resources or
playground pages on the product site and in the repository's marketing or landing app.
Anything on that list is vetoed as already-shipped, never recommended again.

## 2. Generate demand phrases

Turn the buyer's job into up to 12 tool-shaped phrases a stranger would type, for example
"<job> checker", "<format> validator", "<cost> calculator", "<artifact> generator",
"<artifact> template", "<thing> grader", "<A> to <B> converter". Most phrases come from
the buyer's own recurring work: the checks, conversions, templates and calculations they do
whatever product they use. At most two phrases may be about choosing a product, such as a
cost comparison against the category's best-known incumbent; do not let them crowd out the
work phrases. Prefer the buyer's words from the product page over the product's internal
names. Drop anything matching exclude.

## 3. Read the results page

Search each phrase. For each, record the top results you actually saw: URL, whether it is a
working free tool as SCORING.md defines it, and its visible weaknesses. Assign the demand
and winnability labels from SCORING.md and say which results you judged. Discard phrases
labelled demand none.

## 4. Estimate the build effort

For each remaining phrase, search /home/user/project for code that already does the core
input-to-output work: parsers, validators, formatters, scoring or pricing rules, templates,
format converters, schema checks, calculators, or network checks the product already runs.
Read it and cite path:line. Judge whether a public page could reuse it without customer
data or visitor credentials. Classify build effort with SCORING.md. No reusable code is not
a failure: a simple calculator or generator written fresh can still be low effort.

## 5. Apply vetoes, then score and choose

Apply every veto in SCORING.md before scoring. A vetoed candidate goes to the rejected list
with the veto name and the evidence that triggered it. Score survivors with the rubric and
choose the pick with the eligibility and tie-break rules in SCORING.md. Estimate upkeep for
the pick.

## 6. Write the report

Follow REPORT.md exactly. The pick gets the full section, the two best other survivors get a
paragraph, any remaining survivors get one line, and every rejected candidate gets one line.
If no survivor is eligible, write Status: complete with "No tool worth building" and the
evidence for that verdict. Use Status: incomplete only when you could not gather the
evidence (for example the product page and repository were both unreadable, or search
failed), and say what is missing.
