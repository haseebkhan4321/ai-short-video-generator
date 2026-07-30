# Up-front budget approval

Approve a whole video's projected spend once, instead of clicking through every paid
step. Off unless someone uses it: with no up-front approval, every paid step waits for
a human exactly as before.

## The projection

`CostEstimator.estimate_video(target_minutes)` returns a breakdown, not a number:

```
Script                 Rs 8.40
15 images              Rs 168.00
Narration, merge, render  Free
Projected total        Rs 176.40
```

A breakdown because "Rs 176" invites a shrug and "15 images at Rs 11.20 each" invites a
decision.

Part count comes from `CostEstimator.expected_parts`, which mirrors what
`split_service` actually does — it fills each part up to
`WORDS_PER_MINUTE × TARGET_MINUTES_PER_PART` words. That lives in its own function
precisely so the projection cannot drift from the split, because a projection that
disagreed with the steps it authorizes would be worse than no projection. A test
asserts the two agree.

## Budget against committed, not spent

This is the part worth reading twice.

```python
committed = total_cost_usd + sum(estimates of steps that are approved or running)
headroom  = budget_approved_usd - committed
```

`total_cost_usd` only counts money already recorded, and a step records its actual cost
when it *finishes*. Budgeting against spend alone would authorize twelve image steps
against the same headroom, because queueing them moves no money. Committed spend counts
what is already promised.

## Releasing steps

`release_pending_steps` walks pending steps in creation order and stops at the first one
that does not fit — it does not skip an expensive part to fit a cheaper one later.
Running parts out of order to squeeze under a budget would be a surprising thing for it
to do unprompted.

Free steps always fit, so they are released too. An up-front approval means "run this
video"; narration waits for a click because it is slow, not because it costs anything.

It runs in two places: when the budget is approved (releasing whatever is already
pending), and in `_advance` after the split (so the image and narration steps it just
created start on their own). A no-op when there is no up-front approval.

## Its own permission

`step.approve_budget`, separate from `step.approve_paid`. Approving one step with its
cost on the screen and pre-authorizing everything are different levels of trust — the
same reason `step.override_budget` is separate.

Held by **Owner** by default, not Producer. A Producer can approve spend a step at a
time; pre-authorizing a whole pipeline is an owner-level decision.

## The cap still applies

`MAX_COST_PER_VIDEO` is unchanged. Authorizing past it needs `step.override_budget`,
exactly as approving a single step past it does. Since headroom can never exceed the
authorized amount, releasing steps within headroom is always within the cap.

## Withdrawing

`revoke_budget` clears the approval. It only affects what has not started: work already
queued stays queued, because a task cannot be unsent and pretending otherwise would be
worse than saying so. The UI says this on the confirmation.

## Amounts are entered in rupees

The UI shows PKR, so the form takes PKR and `pkr_to_usd` converts at the edge. Every
stored cost stays USD — two currencies in the database would be a bug waiting to
happen. Blank authorizes the projected total; anything unparseable falls back to it
rather than erroring.

## Tests

`apps/videos/tests/test_budget.py`, 38 tests: the projection agreeing with per-step
estimates, committed-vs-spent accounting, stopping at the first step that does not fit,
the cap, `force`, free steps being released, the split releasing on its own, the
permission split, and the PKR round trip.
