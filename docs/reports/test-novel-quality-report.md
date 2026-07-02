# Test Novel Quality Report

Sample path: `generated/longchain-webnovel/chapters/`

Observed scope: 119 chapters, 815,882 characters, average 6,856 characters per chapter.

## Overall Rating

Overall quality: C+ as a publishable long-form product, B for single-chapter prose texture.

The prose is atmospheric and readable. The setting has a strong civic-folklore/institutional-suspense flavor. However, the manuscript is not suitable for direct publication because continuity, protagonist identity, repeated structure, motif load, and metadata leakage are production blockers.

## Publishability

Not suitable for direct publication.

Blocking evidence:

- Chapter 072 contains a full JSON wrapper with `copyright_boundary`, `notes`, and `text`.
- Chapter 097 contains a `{"text": ...}` wrapper.
- Lead identity drifts across `顾砚秋`, `江砚`, `沈砚`, and `阿照`.
- Core organization names drift across `遗簿库`, `巡遗司`, `夜档司`, `北档房`, and `夜档库`.
- Late chapters repeatedly use the same structural chain: abnormal object, material test, bureau pressure, rule-based counter, old-debt hook.

## Platform Fit

Best fit: 知乎盐言 / 豆瓣阅读 / 番茄悬疑 after heavy control-layer revision.

Weak fit: 起点 and 飞卢 in current form. The book lacks a clean progression system, visible reward ladder, stable antagonist pressure, and frequent hard payoffs.

## Opening Quality

The opening has a strong hook: night archive, missing pages, civic relic mechanisms, and a debt-like unresolved case ledger. The problem is that the named lead begins as `顾砚秋`, while later chapters assign lead functions to `江砚`, `沈砚`, and `阿照` without a designed POV transfer.

## Mainline Structure

The mainline starts as missing registry/debt cases, expands into district machines and hidden tax mechanisms, then keeps adding bridge, lamp, well, paper, ash, seal, and tax devices. It does not reliably convert expansion into arc answers.

## Character Stability

Name counts in the 119-chapter sample:

- `顾砚秋`: 907
- `江砚`: 1,610
- `沈砚`: 2,017
- `阿照`: 2,017
- `沈槐`: 1,122

This is not a deliberate ensemble. It is protagonist-slot drift.

## Organization Stability

Observed core organization counts:

- `夜档司`: 975
- `巡遗司`: 253
- `北档房`: 250
- `遗簿库`: 88
- `夜档库`: 45

The organization hierarchy is unclear because old names are reused as if they are equivalent operating bodies.

## Chapter Repetition

Late sample fingerprint, chapters 105-119:

- 14 of 15 chapters include ash/material testing patterns.
- Most include bureau pressure or procedural blocking.
- Every sampled tail is classified as an old-debt hook.

This produces strong AI-template feel even when individual sentences are polished.

## Motif Overload

Total motif mentions:

- `纸`: 3,679
- `灰`: 2,482
- `灯`: 2,733
- `井`: 2,253
- `印`: 1,563
- `签`: 1,093
- `债`: 729
- `税`: 696

The motif system is no longer selective. It has become the default vocabulary of every case.

## Antagonist Design

The manuscript repeatedly uses “有人” or temporary officials as pressure sources. This creates intrigue but not durable antagonism. A long-form arc needs a visible proxy, a public identity, signatures, current wins, and recurring proactive actions.

## Foreshadowing And Payoff

The sample opens and escalates many clues: missing lines, old debts, missing seals, old wells, lamp contracts, tax slips, bamboo tallies. The system quality report claimed no overdue hooks, but textual reading shows the real reader experience is expansion-heavy and payoff-thin.

## Long-Form Stability

Unstable. The book can continue generating chapters, but the longer it runs, the more it amplifies drift and repetition.

## AI Feel

High in late chapters due to repeated beat order, repeated proof vocabulary, repeated bureau-pressure scenes, and repeated old-debt final hooks.

## Strengths To Preserve

- strong premise and civic-folklore atmosphere;
- concrete craft/forensic details;
- pressure between ordinary livelihood and bureaucratic procedure;
- readable scene rhythm;
- local humor that can release tension.

## Must Fix

- lock lead and organization canon;
- block JSON/metadata leakage;
- require chapter state after every chapter;
- prevent repeated chapter fingerprints;
- cap motif usage;
- track debt/liability as structured state;
- require visible villain operations;
- force payoff windows at 10-chapter intervals;
- generate structured revision tasks for every gate failure.
