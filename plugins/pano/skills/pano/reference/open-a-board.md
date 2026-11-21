# Opening a board, adding a project, moving one

A person has one board artifact. Each project is a key under `projects/`.

## Opening the board

Once per person.

1. Copy `assets/board.html` from this skill's folder to the scratchpad and publish it with the Artifact tool, with `capabilities: {"db": {}, "user": {}, "downloads": true}`.
2. Add the first project (below).

## Adding a project

1. `set` `projects/<key>`: `name`, `goal`, `seq: 0`, and the `counters` the project numbers by hand.
2. Add the key to the project's `.claude/tezgah.toml`:

    ```toml
    [board]
    project = "<key>"
    ```

3. Save the board's address in that project's memory as a reference note named `work-board`, with one index line.

## Changing the page

Read the artifact, edit the file it gives, and publish to the same address. The cards stay. A change every board should have goes into `assets/board.html` here as well.

## Moving a board from the first layout

The first layout kept one artifact per project, with `board/meta`, `tasks/` and `briefs/` at the root and a `group` field on each card.

1. Dump it: `list` each collection with `out_dir`.
2. Map `group` with the user. A version or a phase becomes a `milestone`, a part of the product an `area`, a kind of work a `kind`. Show the distinct values as a table and ask; do not guess the mapping.
3. Set `ball`: a card whose `owner` names the user becomes `user`; a `blocked` card becomes `user` or `external` by what its note says; every other open card is `agent`.
4. `ref` becomes `prs`, as numbers. `at` stays. `created` is unknown for old cards and is left out.
5. Write the documents under `projects/<key>/` in batches of at most 50, then compare the count per status with the dump.
6. Leave the old board as history, with a line at its top saying where the work went.
