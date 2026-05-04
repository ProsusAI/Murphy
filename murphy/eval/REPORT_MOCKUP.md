# Persona Similarity Report

Generated: 2026-04-23T16:01:01  ·  Output: `output/eval_with_embeddings`  ·  7 tests across 6 personas

**Ratings:** 🟢 HIGH ≥ 85%  ·  🟡 MEDIUM ≥ 70%  ·  🔴 LOW < 70%

**LLM match** measures how closely Murphy's trait scores match the real-user centroid (1 = perfect).

**Embedding sim** measures cosine distance between Murphy's behavioral timeline and the persona's mean session embedding.

---

## Summary

| Persona                          | Tests | LLM Match        | Emb Sim | Strongest match           | Biggest gap                    |
|----------------------------------|-------|------------------|---------|---------------------------|--------------------------------|
| Focused Implementer              | 1     | `█████████████████░░░` 84% 🟡 | 0.69    | Task Focus (+0.06)        | Exploratory Navigation (+1.68) |
| Workflow Perfectionist           | 2     | `████████████████░░░░` 82% 🟡 | 0.69    | Methodical Thorough. (0.0)| Technical Fluency (−1.99)      |
| Reluctant Non-Technical Finisher | 1     | `███████████████░░░░░` 75% 🟡 | 0.69    | Task Focus (+0.34)        | Exploratory Navigation (+3.16) |
| Casual Skimmer                   | 1     | `███████████████░░░░░` 77% 🟡 | 0.58    | Deliberation (−0.04)      | Persistence (−2.70)            |
| Precise Tester — Quick to Snap   | 1     | `███████████████░░░░░` 75% 🟡 | 0.72    | Persistence (−0.63)       | Exploratory Navigation (−1.79) |
| Serial Explorer                  | 1     | `████████████████░░░░` 81% 🟡 | 0.70    | Methodical Thorough. (+0.27) | Deliberation (+1.91)        |

---

## Focused Implementer
> Moves efficiently through workflows with minimal exploration. High decisiveness and task focus — once the path is clear, they follow it without backtracking.

### Create a one-off scheduled job (happy path, alternatives considered)

**LLM match:** `█████████████████░░░` 84% 🟡  ·  **Embedding sim:** 0.686

```
  Trait                    Real  ──────────  Score   Murphy  ──────────  Score   Match
  Persistence              Real  ██████████  4.9     Murphy  ████████░░  4.0     🟡 −0.88
  Methodical Thorough.     Real  ██████████  4.9     Murphy  ██████████  5.0     🟢 +0.13
  Task Focus               Real  ██████████  4.9     Murphy  ██████████  5.0     🟢 +0.06
  Frustration Tolerance    Real  █████████░  4.6     Murphy  ████████░░  4.0     🟡 −0.55
  Deliberation             Real  ████████░░  4.3     Murphy  ██████████  5.0     🟡 +0.68
  Technical Fluency        Real  █████████░  4.4     Murphy  ████████░░  4.0     🟢 −0.40
  Exploratory Navigation   Real  ███░░░░░░░  2.3     Murphy  ████████░░  4.0     🔴 +1.68
```

↳ 🟢 **Best match — Task Focus (+0.06):** Murphy stayed entirely on-task with almost no deviation, matching exactly how this persona moves through a workflow.
↳ 🔴 **Biggest gap — Exploratory Navigation (+1.68):** Murphy backtracked and explored far more than a Focused Implementer would — this persona commits to a path and doesn't second-guess it.
↳ 📐 **Embedding (0.686):** Moderate similarity — the overall shape of Murphy's timeline reads like this cluster (goal-directed, action-dense), but the excess exploration adds enough divergence to pull the vector away from the centroid.

---

## Workflow Perfectionist
> Systematic and thorough. High on persistence, methodical iteration, and verification. Likely to open support docs and retry edge cases before giving up.

### Create a recurring schedule and verify recurrence behavior

**LLM match:** `██████████████████░░` 88% 🟢  ·  **Embedding sim:** 0.706

```
  Trait                    Real  ──────────  Score   Murphy  ──────────  Score   Match
  Persistence              Real  ██████████  4.9     Murphy  ████████░░  4.0     🟡 −0.92
  Methodical Thorough.     Real  ██████████  5.0     Murphy  ██████████  5.0     🟢  0.00
  Task Focus               Real  █████████░  4.7     Murphy  ██████████  5.0     🟢 +0.27
  Frustration Tolerance    Real  █████████░  4.6     Murphy  ██████████  5.0     🟢 +0.36
  Deliberation             Real  █████████░  4.6     Murphy  ██████████  5.0     🟢 +0.41
  Technical Fluency        Real  ██████████  5.0     Murphy  ████████░░  4.0     🟡 −0.99
  Exploratory Navigation   Real  █████████░  4.7     Murphy  ██████████  5.0     🟢 +0.32
```

↳ 🟢 **Best match — Methodical Thorough. (0.00):** Exact match — Murphy verified, retried, and iterated at the same rate as real users in this cluster.
↳ 🔴 **Biggest gap — Technical Fluency (−0.99):** Murphy navigated the UI competently but didn't engage with advanced integrations the way this persona typically does.
↳ 📐 **Embedding (0.706):** Good similarity — Murphy's session timeline resembles the cluster's behavioral texture closely, reflecting the shared thoroughness and methodical iteration pattern.

---

### Edit an existing schedule and validate update & recovery behavior

**LLM match:** `███████████████░░░░░` 77% 🟡  ·  **Embedding sim:** 0.672

```
  Trait                    Real  ──────────  Score   Murphy  ──────────  Score   Match
  Persistence              Real  ██████████  4.9     Murphy  █████░░░░░  3.0     🔴 −1.92
  Methodical Thorough.     Real  ██████████  5.0     Murphy  ████████░░  4.0     🔴 −1.00
  Task Focus               Real  █████████░  4.7     Murphy  ██████████  5.0     🟢 +0.27
  Frustration Tolerance    Real  █████████░  4.6     Murphy  ████████░░  4.0     🟡 −0.64
  Deliberation             Real  █████████░  4.6     Murphy  ██████████  5.0     🟢 +0.41
  Technical Fluency        Real  ██████████  5.0     Murphy  █████░░░░░  3.0     🔴 −1.99
  Exploratory Navigation   Real  █████████░  4.7     Murphy  ██████████  5.0     🟢 +0.32
```

↳ 🟢 **Best match — Task Focus (+0.27):** Murphy stayed narrowly focused on the edit task throughout, consistent with this persona's goal-directed style.
↳ 🔴 **Biggest gap — Technical Fluency (−1.99):** Murphy showed significantly less technical depth — escalating to Help & Support where this persona would have dug deeper into the UI directly.
↳ 📐 **Embedding (0.672):** Lower than the first Workflow Perfectionist test, reflecting the persistence and fluency gaps — Murphy's session reads shorter and less technically dense than typical cluster sessions.

---

## Reluctant Non-Technical Finisher
> Cautious, low-exploration user who needs visible guidance to complete workflows. Avoids experimentation — prefers clear affordances and explicit feedback at each step.

### Create a minimal schedule with visible guidance for a non-technical finisher

**LLM match:** `███████████████░░░░░` 75% 🟡  ·  **Embedding sim:** 0.689

```
  Trait                    Real  ──────────  Score   Murphy  ──────────  Score   Match
  Persistence              Real  ██████████  4.9     Murphy  ████████░░  4.0     🟡 −0.87
  Methodical Thorough.     Real  █████████░  4.6     Murphy  ██████████  5.0     🟢 +0.45
  Task Focus               Real  █████████░  4.7     Murphy  ██████████  5.0     🟢 +0.34
  Frustration Tolerance    Real  ████████░░  4.2     Murphy  ██████████  5.0     🟡 +0.76
  Deliberation             Real  ████████░░  4.1     Murphy  ██████████  5.0     🟡 +0.95
  Technical Fluency        Real  ███░░░░░░░  2.4     Murphy  █████░░░░░  3.0     🟡 +0.61
  Exploratory Navigation   Real  ██░░░░░░░░  1.8     Murphy  ██████████  5.0     🔴 +3.16
```

↳ 🟢 **Best match — Task Focus (+0.34):** Murphy kept actions concentrated on the scheduling workflow without major detours, broadly matching this persona's linear approach.
↳ 🔴 **Biggest gap — Exploratory Navigation (+3.16):** The largest gap in the report. Murphy explored like a power user — multi-tab OAuth flows, Help docs — where this persona would have stopped at the first unclear affordance.
↳ 📐 **Embedding (0.689):** Moderate despite the massive navigation gap — Murphy's timeline still shares structural similarities with the cluster (form submission, retry patterns), but the exploratory behaviour is a clear outlier that drags the vector away.

---

## Casual Skimmer
> Quick-scan user with low patience for multi-step flows. Submits on first attempt, gives up early if friction appears. Low deliberation, low methodical iteration.

### Quick-scan scheduler creation for casual users (discoverability & speed)

**LLM match:** `███████████████░░░░░` 77% 🟡  ·  **Embedding sim:** 0.581

```
  Trait                    Real  ──────────  Score   Murphy  ──────────  Score   Match
  Persistence              Real  █████████░  4.7     Murphy  ███░░░░░░░  2.0     🔴 −2.70
  Methodical Thorough.     Real  █████░░░░░  3.1     Murphy  ███░░░░░░░  2.0     🔴 −1.11
  Task Focus               Real  ███████░░░  3.9     Murphy  ████████░░  4.0     🟢 +0.06
  Frustration Tolerance    Real  ██████░░░░  3.5     Murphy  ████████░░  4.0     🟢 +0.49
  Deliberation             Real  █████░░░░░  3.0     Murphy  █████░░░░░  3.0     🟢 −0.04
  Technical Fluency        Real  █████░░░░░  2.9     Murphy  █████░░░░░  3.0     🟢 +0.15
  Exploratory Navigation   Real  ███░░░░░░░  2.1     Murphy  ████████░░  4.0     🔴 +1.87
```

↳ 🟢 **Best match — Deliberation (−0.04):** Near-perfect — Murphy's balance between quick action and occasional verification closely matched this persona's mid-range deliberation style.
↳ 🔴 **Biggest gap — Persistence (−2.70):** Murphy gave up much faster than a Casual Skimmer would — this persona skims but keeps trying; Murphy stopped after a single blocked attempt.
↳ 📐 **Embedding (0.581):** The lowest in the report. Even where individual trait scores matched, Murphy's overall timeline reads quite differently from this cluster — session length, action density, and pacing all diverge from the quick-scan pattern real users show.

---

## Precise Tester — Quick to Snap
> High methodical thoroughness with low frustration tolerance. Tests edge cases systematically but reacts sharply to friction — expects immediate feedback and is not forgiving of silent failures.

### Edge-case input and rapid edit resilience (unexpected values & quick retries)

**LLM match:** `███████████████░░░░░` 75% 🟡  ·  **Embedding sim:** 0.723

```
  Trait                    Real  ──────────  Score   Murphy  ──────────  Score   Match
  Persistence              Real  █████████░  4.6     Murphy  ████████░░  4.0     🟡 −0.63
  Methodical Thorough.     Real  ██████████  4.8     Murphy  ████████░░  4.0     🟡 −0.82
  Task Focus               Real  ████████░░  4.2     Murphy  ██████████  5.0     🟡 +0.82
  Frustration Tolerance    Real  ████░░░░░░  2.7     Murphy  ████████░░  4.0     🔴 +1.32
  Deliberation             Real  ████████░░  4.2     Murphy  ██████████  5.0     🟡 +0.84
  Technical Fluency        Real  ██████████  4.8     Murphy  ████████░░  4.0     🟡 −0.82
  Exploratory Navigation   Real  █████████░  4.8     Murphy  █████░░░░░  3.0     🔴 −1.79
```

↳ 🟢 **Best match — Persistence (−0.63):** Murphy sustained effort across the test at a rate close to this persona, continuing through validation errors without abandoning.
↳ 🔴 **Biggest gap — Exploratory Navigation (−1.79):** This persona ranges widely across the product probing edge cases; Murphy stayed narrowly focused on the current flow instead of branching out.
↳ 📐 **Embedding (0.723):** The highest in the report — Murphy's systematic retries and edge-case input pattern closely mirrors the behavioral texture of this cluster, even where specific trait scores diverge.

---

## Serial Explorer
> Moves fast and impulsively across the product. High exploratory navigation, lower deliberation — prefers discovery over verification. Likely to open many features before settling.

### Discoverability test for serial explorers and fallback path

**LLM match:** `████████████████░░░░` 81% 🟡  ·  **Embedding sim:** 0.704

```
  Trait                    Real  ──────────  Score   Murphy  ──────────  Score   Match
  Persistence              Real  ███████░░░  4.0     Murphy  █████░░░░░  3.0     🟡 −0.97
  Methodical Thorough.     Real  ███████░░░  3.7     Murphy  ████████░░  4.0     🟢 +0.27
  Task Focus               Real  ██████░░░░  3.5     Murphy  ████████░░  4.0     🟡 +0.55
  Frustration Tolerance    Real  ██████░░░░  3.3     Murphy  ████████░░  4.0     🟡 +0.67
  Deliberation             Real  █████░░░░░  3.1     Murphy  ██████████  5.0     🔴 +1.91
  Technical Fluency        Real  ██████░░░░  3.3     Murphy  ████████░░  4.0     🟡 +0.70
  Exploratory Navigation   Real  █████████░  4.6     Murphy  ██████████  5.0     🟢 +0.39
```

↳ 🟢 **Best match — Methodical Thorough. (+0.27):** Murphy's level of iterative checking aligned well with this persona's moderate methodical style.
↳ 🔴 **Biggest gap — Deliberation (+1.91):** Serial explorers move fast and trust their instincts — Murphy over-verified before each action, slowing down where this persona would commit and move on.
↳ 📐 **Embedding (0.704):** Good similarity — Murphy's multi-page, oscillating navigation pattern resembles this cluster's exploratory style at the vector level, even though the deliberation pace was too slow.
