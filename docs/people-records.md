# People records

A project's people records hold one lasting record per person the project knows. This is the
first slice of the records design (#435): Tin's own workflows write them. Segments, a commit
log, agent copies (`pull_records`, `commit_record_changes`) and the `/people` view come later.
`src/tin_lite/people_records.py` is the only writer.

## Tables

| Table | Holds |
|---|---|
| `records` | One row per person, with a `type` (only `person` today) and where it first came from |
| `record_identifiers` | How a record is recognized: a LinkedIn member ID or profile slug, unique per project |
| `record_fields` | Field definitions: built-in today, custom later without a migration |
| `record_values` | One current value per record and field, with its lineage |
| `record_events` | The timeline: `reacted`, `commented`, `invited`, `accepted`, `withdrawn` |
| `record_suppressions` | A hash of each identifier of a person the founder asked Tin to forget |

## Recognizing a person

`linkedin_identifiers` reads a profile URL or URN:
- `/in/ACo…` and `urn:li:fsd_profile:ACo…` are LinkedIn's own profile ID (`linkedin_member`);
- any other `/in/<slug>` is the public slug (`linkedin_slug`), compared without case.

`upsert_person` returns the record that any of the given identifiers already names, or makes
one. It takes a per-project lock, so two reads of the same person never create two records.

When one read names two records (a slug on one, a member ID on the other), they merge:
- the older record survives, and the newer points at it with `merged_into`;
- identifiers move to the survivor;
- the survivor keeps its own values, and a field only the newer record had moves over;
- events stay where they were written, and reads count them under the survivor.

## Values

Each value records:
- who set it: a run's ID or a member's user ID (`set_by_kind` is `run` or `member`);
- when, and a one-line reason;
- the definition it was computed under, such as the ICP file's revision, so a changed
  definition can show old values as stale.

An empty value can still carry a reason, such as an ICP score the model couldn't support.
A run never replaces a value a member set. A write that changes nothing keeps the earlier
value and its time.

The built-in fields are:
- `name`, `headline` (text);
- `linkedin_relationship` (`connected`, `pending` or `none`);
- `icp` (which named profile in the ICP file);
- `icp_fit` (a number from 0 to 1).

## Events

Events are only added. Each has an `event_key` that is unique per project: an engagement
keys on the post, the person and the kind, so reading the same post again adds nothing. An
event written to a record that later merged counts under the survivor.

## Forgetting and deletion

`forget` deletes the person and every record merged into them, with their values, events and
identifiers. It keeps a SHA-256 of each identifier, salted with the project ID, so the next
read refuses them; `upsert_person` returns `None` for that person. Forgetting is per project.

Deleting a project purges all six tables (`purge_project_data`).
`tests/test_project_purge.py` fails if a new table that holds project data is missing from
the purge.
