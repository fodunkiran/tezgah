# Board schema

Every collection is under `projects/<key>/`; `<key>` is the project's key, `board.project` in `.claude/tezgah.toml`.

| Path | Holds |
|---|---|
| `projects/<key>` | The project document |
| `projects/<key>/milestones/<id>` | A milestone |
| `projects/<key>/tasks/<id>` | A card |
| `projects/<key>/briefs/<id>` | A card's long description |
| `projects/<key>/waves/<id>` | A landing plan |
| `projects/<key>/archive/<milestone id>/tasks/<id>` | A closed card of a closed milestone |
| `projects/<key>/archive/<milestone id>/briefs/<id>` | Its brief |

## The project document

| Field | Meaning |
|---|---|
| `name` | The project's name on the page |
| `goal` | One sentence: what the current stretch of work is for |
| `seq` | The last card number given |
| `counters` | The next free numbers sessions reserve, by name (`ADR`, `migration`) |

## A milestone

| Field | Meaning |
|---|---|
| `title` | What it is: a version, a phase, a gate |
| `exit` | A short list of what must be true to close it |
| `due` | A day, when there is one |
| `state` | `open` or `closed` |
| `order` | Its place on the page |

## A card

Ids are `t001`, `t002`, …, numbered from `seq`; four digits from `t1000` on.

| Field | Meaning |
|---|---|
| `title` | The outcome, under 90 characters |
| `status` | See the table below |
| `ball` | Who has to act next: `agent`, `user` or `external` |
| `waiting` | With `ball: external`: who or what the card waits for |
| `milestone` | The id of its milestone; absent when it belongs to none |
| `area` | A free tag for the part of the product |
| `kind` | `feature`, `fix`, `debt`, `decision`, `chore` or `research` |
| `order` | A number; the lowest goes first in the queue |
| `deps` | Ids of open cards that must close first; a closing card removes itself from these lists |
| `owner` | The session that has the card, while it is `doing` |
| `prs` | Its pull request numbers |
| `reqs` | The requirement ids and decision records it touches (`F-75`, `ADR 0083`) |
| `wave` | The id of the wave it lands with |
| `follow` | Ids of the cards opened to continue it |
| `note` | One sentence under 240 characters: what came out, what it waits for, why it is stuck |
| `reply` | The user's answer to a `review` or `blocked` card |
| `brief` | `true` when `briefs/<id>` exists |
| `src` | `user` or `agent`: who wrote the card |
| `created`, `started`, `closed` | Days (`YYYY-MM-DD`) |
| `at` | The day of the last status change |

| `status` | Means |
|---|---|
| `inbox` | The user wrote it; nobody has shaped it yet |
| `todo` | Queued; the lowest `order` goes first |
| `doing` | A session has it (`owner`) |
| `review` | Finished, waiting for the user's word |
| `blocked` | Cannot go on; `note` says why or asks |
| `later` | An idea kept out of the queue until the user pulls it in |
| `done`, `dropped` | Closed |

`status` says where the work is; `ball` says whose move it is. The page's "your turn" band lists every open card with `ball: user`, whatever its status: a release only the user can cut is `todo` with `ball: user`.

## A brief

`text`: everything too long for the card.

## A wave

A landing plan, written by whoever orchestrates, so that a fresh session can pick a wave up.

| Field | Meaning |
|---|---|
| `title` | What the wave is |
| `state` | `planning`, `running`, `landing` or `closed` |
| `cards` | The ids of its cards |
| `order` | Pull request numbers in landing order |
| `base` | The integration commit the pieces were checked on |
| `tree` | The tree of the verified, integrated state |
| `note` | What a session picking it up must know, under 500 characters |
| `at` | The day of the last change |

## The archive

When a milestone closes, its closed cards and their briefs move to `archive/<milestone id>/` in batches (a `set` there and a `delete` here in one `batch`). The live collections keep open work, so the reads stay small.

## Export

A dump of the project is each collection listed with `ArtifactData`'s `out_dir`: the project document, `milestones`, `tasks`, `briefs`, `waves`. Take one at every milestone close and keep it where the project keeps its archives. The page offers the same as a download.
