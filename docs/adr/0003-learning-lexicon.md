# ADR-0003. A learning lexicon with human review

- Status: accepted
- Date: 2026-10-19

## Context

The noise filter and the question detector rely on word lists. Real chats change and the
lists age. The owner wants the system to accumulate experience: count repeating words and
phrases, keep the significant ones, learn from AI feedback later, and forget what stops
appearing — while staying explainable and safe from poisoning (one spammer repeating a
phrase must not rewrite the rules).

## Decision

- The lexicon is **data in the database** (`lexicon_terms`), seeded from the built-in
  `.txt` lists. A term has a kind, language, status (candidate, active, rejected, dormant),
  source (seed, stats, ai, human), statistics (occurrences, distinct chats, distinct authors,
  log-odds score), up to three example message keys and decision metadata.
- **Statistics propose, a human decides.** Mining (`learning/`) scores phrases by log-odds
  against the background with an informative prior and applies thresholds on occurrences,
  distinct chats and distinct authors. Passing phrases become CANDIDATEs; they never act
  until accepted. Rejected terms are never proposed again.
- **Forgetting is dormancy, not deletion.** Mined active terms not seen for a configured
  time become DORMANT and stop being used; they wake up if they appear again.
- **A revision number** counts changes of the ACTIVE set. Stages that read the lexicon
  (`noise`, `enrich`) remember the revision they processed with; `process` reprocesses a
  stage whose revision is behind, using the existing stage-reset mechanism.
- **Measure before improving.** `chatradar eval` computes precision, recall and F1 of the
  filter against ground truth: a truth file written by the synthetic generator, or human
  labels from the panel. Tests fail when quality drops.
- AI later becomes one more *source* of candidates and a judge on disagreements; the model
  and queue are ready for it (`source=ai`), the model calls are not part of this ADR.

## Consequences

- Rule behavior depends on data; a rule change is a lexicon revision, visible and reversible.
- The pipeline needs a lexicon snapshot as input (`StageDeps.lexicon`), staying pure.
- Mining on folded surface forms (no stemming yet) produces inflected duplicates; see the
  backlog.
- Defaults for thresholds are untested on real data; tuning is a recorded next step.
