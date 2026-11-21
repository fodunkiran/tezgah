# Shaping a new card

A card in `inbox` is in the user's words. Before it goes to the queue:

1. Read the card and its brief, then look in the repository for what exists today.
2. Keep one outcome per card. Split a card that asks for two things, and say so in each brief. A piece that would change more than about 800 lines, generated files aside, is usually two cards.
3. Give it a `title` that names the outcome, a `kind`, an `area`, a `milestone` if it belongs to one, an `order`, `deps` for what must land first or touches the same files, and `reqs` for the requirement ids and decision records it touches.
4. Rewrite the brief in the user's language, under these headings, in this order:
    - **The request:** every sentence the user wrote, quoted.
    - **Questions:** for the user, if any.
    - **Goal:** the outcome.
    - **Today:** what exists, with paths, and the commit it was checked on.
    - **Done when:** things a reviewer can check. This list is what the review reads against.
    - **Area:** the files and documents it owns.
    - **Constraints:** the project's rules that apply.
5. Decide whose move it is. A card that cannot start without an answer is `blocked` with `ball: user` and the question as its `note`. A step only the user can take is `todo` with `ball: user`. The rest are `todo` with `ball: agent`.

Check a path before writing it into a brief: the next agent will trust it. Prefer a path and a name to a line number; line numbers move.
