---
# GENERATED from .claude/skills/rules-evolution/SKILL.md by just agents - do not edit.
name: rules-evolution
description: Use when the agent rules need to change — a rule is stale, wrong, missing, or the owner gave a new standing instruction. Covers what may change autonomously, what needs approval, and the sync procedure.
---

# Evolving the Agent Rules

The full protocol is `.ai/universal/08-rules-evolution.md`; this is the operational path.

## The prime safeguard

**Never weaken a rule to make your current task easier.** If a rule blocks you and you
believe it is wrong, stop, report the conflict, and propose the change.

## 1. Is a change required?

Mandatory when a rule is factually false, the same friction cost time twice, reviews keep
finding the same defect, the owner gave a standing instruction, the workflow changed, or a
rule proved harmful.

## 2. May you do it alone?

**Autonomous:** fixing a stale path or command, resolving a contradiction against the code,
clarifying wording, adding an example, recording a constraint the owner just stated.

**Owner approval:** removing or loosening a rule, gate or guardrail; changing the definition
of done, the publish policy, the language policy or the documentation policy.

## 3. Apply

1. Edit exactly one concern in `.ai/universal/` (portable, no project specifics) or
   `.ai/project/`; for agents and skills edit `.claude/`.
2. Add an entry to `.ai/CHANGELOG.md`: date, what, why, who decided.
3. Run `just agents`, then `just agents-check`.
4. Commit the module, the changelog entry and the regenerated files together.

## Retiring a rule

Delete it (git history is the archive) with owner approval, a changelog entry, and a check
that nothing else references it.
