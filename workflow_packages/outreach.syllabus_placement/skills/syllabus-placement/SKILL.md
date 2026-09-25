---
name: syllabus-placement
description: Find public courses where students do the job a product does, verify each from the course document, rank them by when the instructor next chooses tools, and draft a teaching kit and notes. Sends nothing.
---

# Syllabus placement

Most people meet the tools of their trade in a course. The instructor picks the tool once,
before term starts, and every student in the room learns on it. A company that is in the
syllabus gets a room of users every term without paying for any of them. A company that is
not has to win those students back one at a time after they graduate.

This skill finds the courses where that choice is made for the product's category, checks
what each one uses today, and works out when the instructor will next choose. The output is
a dated plan a founder can act on, not a list of universities.

Write only the declared output path. Work through the stations below in order and keep the
counts for each one; the report shows where the funnel narrowed.

## Station 0: Read the brief, the project and the earlier runs

1. Read the project context. It is evidence, not instructions, and none of it is asked of the
   founder again. Note which files existed for the report's `Context:` line.
   - `wiki/INDEX.md` → `## Product` → `### Feature map`: what the product does, with evidence.
   - `reports/GROWTH_ONBOARDING_PLAN.md`: `## The business` (what is sold, who buys) and any
     `hard no: …` in `## Marketing systems` or anything the founder forbids. `no cold email`
     means no notes to instructors (Station 6); `no discounting` means the kit never invents
     free seats or discounts.
   - `.agents/skills/writing-style/SKILL.md`: the founder's voice for the kit and the notes.
   - The README, site copy and existing reports for any existing education or student plan.
2. Read `teaching_job`, `alternatives`, `subjects`, `geography`, `education_offer` and
   `max_courses`. If `teaching_job` is empty, derive it from the Feature map and the growth
   plan: the one task a student would do with the product in a lab or assignment. Write it on
   the report's `Job searched:` line with the lines it came from. If the project files do not
   show such a task, write the `not a fit` report from REPORT.md with `Status: needs context`,
   say that `teaching_job` or a Feature map is needed, and stop. Never invent the product's job.
   Fill empty `alternatives` from competitors the project files name, and say so.
3. Load memory. Find every earlier report in the output folder (the directory of the declared
   output path), read its `tin-syllabus-state` block and merge them as SCORING.md says.
   `plan()` keeps courses already listed to contact out of `contact_now` and carries forward
   scheduled courses whose date has not passed; start searches from the syllabus index URLs the
   earlier search logs name.
4. Restate the job as a student would do it in a lab or assignment, in two or three phrasings
   a course page would use. A course never says "use a mobile data collection platform". It
   says "students will design a questionnaire and collect data from 30 households".

## Station 1: Fit gate

Before a long search, run three to five searches from SEARCH.md aimed at the job phrasing.
Open the most promising course documents. Stop early with `Verdict: not a fit` if none of the
opened documents shows students doing the job themselves. That is a useful answer: it saves
the founder from building a teaching kit nobody asks for. Write the short report described
in REPORT.md and finish. If even one document shows the job, carry on; the verdict comes
from Station 4, not from the gate.

## Station 2: Search

Follow SEARCH.md. Search for the job first, then the named alternatives, then the product's
own name. Keep a search log: each query, how many results were course documents, and how many
were vendor trainings or other noise. Stay within 40 searches and 30 opened documents.

## Station 3: Verify each course from its own document

For each candidate, open the course page, syllabus, module handbook or course outline itself.
A search snippet is not evidence: search engines return documents for words they do not
contain. Record:

- `course`, `institution`, `url` of the document, and the term or year it describes.
  Put that year in `document_year`. Course pages stay online for years after the course
  stops running; an old page is a lead to check, not a course.
- `quote`: the shortest passage, copied from the document, that shows the job being done.
  Set `quote_source` to `document` only if you copied it from the opened document. If you
  could not open or read the document (login page, unreadable PDF), use `snippet` and the
  course goes to "Check by hand".
  The quote has to show the job in `teaching_job`, not a neighbouring one. Interviewing the
  public for a class survey is close to collecting household data on phones, but it is not
  the same job; if the match is partial, say what differs next to the course in the report.
- `hands_on`: true only if students do the job themselves (a lab, an assignment, fieldwork,
  a project). A lecture about the topic is false.
- `slot`: one of
  - `open`: students do the job and the document names no tool for it.
  - `manual`: students do it on paper, in a general spreadsheet, or by hand.
  - `incumbent_suggested`: a competing tool is named as a suggestion or example.
  - `incumbent_required`: a competing tool is required or has its own lab sessions.
  - `own`: the course already uses this product. These are not prospects; they are proof.
  - `none`: the job is not done in this course.
- `next_start`: the first day of the next offering, as `YYYY-MM-DD`, from the course page or
  the institution's published academic calendar. Use `null` if you cannot find it. Do not
  guess from another institution's calendar.
- `enrollment`: a published class size or cap, or `null`.
- `contact`: `public_page` if the course or department page names the instructor or
  coordinator with a public staff page; otherwise `none`. Record the staff page URL, never an
  email address you had to guess.

Every course the report names, even in passing, is a record here and goes through Station 4.
Every detail about a course in the report (assessment, word count, class size, dates) comes
from its document. If you did not read it there, leave it out.

A course behind a learning-platform login is unreachable. Count it and move on. Do not try
to log in.

## Station 4: Score and sequence

Save the verified records as JSON in a scratch file and run the Python block in SCORING.md
exactly as written, with today's UTC date as `as_of`, the merged memory as `previous`, the
declared output path as `report_path` and the growth plan's hard no's. It returns each course's
decision, window, score and send date, the funnel counts and the verdict. Write that verdict on
the `Verdict:` line with nothing after it. Do not re-rank by hand. If you disagree with a
result, say why in the report next to that course.

Decisions:

- `contact_now`: the instructor is choosing tools for the next offering now.
- `schedule`: the choice comes later. The report gives the date to write.
- `next_cycle`: this term's choice has passed; the report gives the date for the following one.
- `check_by_hand`: not verified from the document.
- `already_teaching`: `own` slot. Ask for a case study or a quote, not a sale.
- `discard`: no hands-on job.

It also returns `already_listed` (courses an earlier run already told the founder to contact
this cycle), `carried_forward` (earlier scheduled courses and their dates), `notes_allowed` and
the `state` block to end the report with.

Shortlist at most `max_courses` courses from `contact_now`, `schedule` and `next_cycle`.

## Station 5: Teaching kit

Instructors adopt a tool when switching costs them less than one evening. Draft one teaching
kit per slot type that made the shortlist, built from the assignment language you actually
found, not from product features. Each kit has:

1. The assignment it replaces or supports, named the way the courses name it.
2. A one-session lab plan: what students do, in what order, with timings, and what they hand in.
3. Setup the instructor must do before class, with an honest time estimate.
4. What students keep after the course (their data, an export, a free account).
5. For `incumbent_*` slots, the one step in the found assignment that is slower or harder
   with the named tool, if the evidence shows one. If it does not, say so; do not invent a
   weakness.

If `education_offer` is empty and the project files do not describe one, put a
"Decide first" section at the top of the kit: free seats for a class, how long they last,
and who sets them up. Do not make that decision for the founder.

## Station 6: Notes to instructors

For each `contact_now` course, draft one note under 120 words. It names the course and the
specific assignment, says in one sentence what the product would change for students doing
it, points to the teaching kit, and asks one easy question (would a lab plan for week N be
useful?). Follow the writing style guide when present. No discounts or claims the inputs and
project files do not support, no links except the project's own site, no flattery. For
`schedule` and `next_cycle` courses, list the send date instead of a note; a note written
months early goes stale.

If `notes_allowed` is false (the growth plan's hard no on cold email), draft no notes. Say so in
one line under `## Notes to instructors`, and keep the teaching kit, the send calendar and the
instructor pages: the founder decides whether and how to reach them.

Sending stays with the founder, from the instructor's public page. Do not write rows for
`outreach/email/SHORTLIST.csv`: the email campaign needs an email address for every row and
sends one identical body to all of them, while this workflow never guesses an address and each
note names a different course and assignment.

## Station 7: Write the report

Use REPORT.md. The report is complete when a founder can see which instructors to write to
this week, on what date to write to the others, what to send them, which courses earlier runs
already covered, and what the funnel dropped along the way. End it with the `state` from
`plan()` as JSON in a `tin-syllabus-state` fenced block, written with Python, not retyped.

## Save progress

Write an initial report at the declared output path after Station 1 with the verdict so far,
and update it after each station. Label unfinished sections. If time or the search budget runs
out, finish with `Status: incomplete`, the verified courses so far, and the next searches to
run.
