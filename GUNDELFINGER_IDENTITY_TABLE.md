# Antibody identification – single & two-antibody logic

Rule set as implemented in `abid/rules.py`. Based on standard exclusion logic
as described in the 12th edition of **Dacie & Lewis, Practical Haematology**.

A **Gundelfinger-style identity table** (reactivity matrix: patients × panel
cells, and patient phenotypes) is produced by the engine and can be dumped
during diagnosis.

## Single-antibody logic

1. List reactive cells (grade >= 1).
2. For each candidate antibody, compute the fraction of reactive cells carrying
   the antibody's antigen(s) — the *coverage score*.
3. The antibody with the highest coverage is the **best single candidate**.
4. A single antibody is `confident` when coverage >= 0.8 and there are >= 2
   reactive cells.
5. Explicit *single exclusions*: antibodies ruled out by reactive cells
   lacking their antigen (the *single_exclusions* list).
6. Informational *rule-outs*: negative cells carrying the antibody's antigen
   (stored as `single_exclusions` informational entries). The engine does
   **not** declare single-antibody proof; a technologist confirms.

## Two-antibody logic

1. For each ordered pair (A, B), check *pair validity*:
   - every reactive cell carries A or B (or both);
   - every negative cell carries neither A nor B.
2. Score = fraction of reactive cells covered by A ∪ B.
3. Require each antibody in the pair to support at least one reactive cell,
   otherwise the pair is clinically meaningless (e.g. anti-A1 + anti-K on a
   pure anti-K panel).
4. A pair is `confident` when coverage >= 0.8.
5. Under coverage, the engine reports the top pair(s) and suggests that a
   two-antibody identification be pursued (e.g. by an eager or prozone
   reaction check, adsorption, or enhanced panel).

## Auto-control handling

If any auto-control cell is positive, the result is flagged as
`auto_control_positive` and the single-antibody call is treated as
unreliable (possible autoantibody). The machine still reports candidates but
flags them for technologist review.

## Limitations

- Single-cell (one reactive cell) cases are not "proof" — they are flagged.
- Two-antibody decomposition is reported with explicit caveat that the
  machine does not prove it; a technologist performs enhancement/adsorption.
- Phenotype data must be accurate; subgroup variants are not fully modeled.
