# ADR: Claim Decision Grain for IRIS Worklist

## Status

Proposed for business validation.

## Context

IRIS currently computes claim attention outputs at the `sinistre x garantie` grain. This is useful for explanation because each guarantee can carry different amounts, rules, and reasons. However, a business worklist for claim handlers should not show the same claim dossier multiple times with different attention levels.

The Smart Decision Support V2 read-only validation confirmed:

- 381,893 scored `sinistre x garantie` rows;
- 231,496 distinct claim root identifiers;
- 119,041 claim roots with multiple guarantee rows;
- 31,341 claim roots with multiple V2 scores;
- 13,889 claim roots with multiple V2 attention levels.

This creates a business interpretation risk: one dossier can appear several times in a worklist with different priorities.

## Decision

The target decision grain for IRIS worklists is:

```text
One row per claim dossier root.
```

The explanatory grain remains:

```text
sinistre x garantie.
```

This means the worklist should display one prioritized dossier, while the detail page keeps the guarantees and their activated signals as supporting context.

## Candidate Aggregation Rule

For the first V2 candidate, the dossier-level score is:

```text
dossier_attention_score = max(guarantee attention scores)
```

The score is not summed across guarantees. This avoids mechanically increasing priority only because a dossier has several guarantees.

Other candidate rules:

- guarantee codes are retained as context;
- distinct activated rules are deduplicated across guarantees;
- main reasons are deduplicated and ordered by awarded points;
- no automatic multi-guarantee bonus is applied;
- original `sinistre x garantie` rows are not modified.

## Consequences

### Scoring

V2 dossier aggregation is a candidate layer above the existing V2 guarantee-level score. It does not replace V1 and does not modify the underlying guarantee-level score.

### API

The future read-only API should expose a dossier worklist endpoint at dossier-root grain, with guarantee-level details available through dossier detail endpoints.

### Angular

The worklist should show one row per claim dossier. The dossier detail page should show the concerned guarantees, rule details, chronology, data confidence, post-inspection context, and statistical atypicality if available.

### Power BI

Power BI can show both grains:

- dossier-level distributions for worklist and management reporting;
- guarantee-level distributions for analytical drill-down.

## Alternatives Rejected

### Keep `sinistre x garantie` as worklist grain

Rejected because it can duplicate dossiers in the handler worklist and create different priorities for the same dossier.

### Sum guarantee scores

Rejected because multi-guarantee dossiers would be mechanically penalized even when the underlying reasons are duplicated or not independently meaningful.

### Add an automatic multi-guarantee bonus

Rejected for V2 candidate. Such a signal requires separate business validation.

## Validation Required

BNA should validate that:

- one worklist row per claim dossier is operationally correct;
- the maximum guarantee score is acceptable as a first conservative aggregation;
- guarantee-level reasons remain visible in dossier details;
- multi-guarantee context should not add points automatically in this phase.

## Non-Goals

This ADR does not:

- modify Claim Attention V1;
- modify VHS;
- integrate ML into the dossier score;
- recalibrate thresholds;
- write to PostgreSQL;
- define the final Angular design.
