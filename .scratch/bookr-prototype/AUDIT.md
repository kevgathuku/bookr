# InvalidStates.scala — accuracy audit (2026-11-01)

Review of `.scratch/prototype/InvalidStates.scala` against the current
domain. Verdict: sections 1, 4 (partly), 5 (partly), 7 capture real
weaknesses — but section 3 models a feature that does not exist, and the
largest invalid-state machinery in the domain is unmodeled.

## Missing (ranked)

1. **Policy resolution** — ✅ Resolved (2026-11-01). `Policy` carries
   optional `venue/category/plan` scopes plus `priority`; `rank` is
   `(specificity, priority)` and `resolve` prepends the all-null baseline
   (priority `-1`, window 0) so `maxBy` cannot fail — total by the same
   construction as `_ensure_baseline`. Fee now requires a
   `Some(Private)` category scope, encoding the `bookr-55d` decision.
2. **Waitlist / promotion / hold lifecycle** — `hold_expires_at` non-null
   exactly while a promotion hold is live is the section-3 pattern in the
   wild; freed seats passing to the queue head on every cancel unmodeled.
3. **Booking invariants** — `one_active_session_booking` (partial unique
   over active statuses), membership↔user↔org match in `clean()`,
   validity window, `CreditInsufficient → 402`, natural-key idempotent
   retries (`DuplicateBooking`).
4. **Session lifecycle** — `cancelled_at` sessions unbookable
   (`_ensure_open`); provider-cancel refunds all + idempotent repeats.
5. **Membership validity window + third plan type** — booking on an
   expired plan is a real invalid state (`_validate_membership` guards);
   `PlanType` is `MONTHLY / CREDIT_PACK / COMPLIMENTARY`, prototype has
   two cases and no dates.

## What holds up

- ID types (every FK is an int) and the nullable-venue convention
  critique (`venue=None` = org-wide by convention only).
- The `was_late / penalty_waived / waived_by` Boolean-blindness callout.
- The `decide` cutoff boundary (`moment > start − window`) is faithfully
  transcribed (`booking/cancellations.py::_apply_cancel`).

## Proposed rework (not yet done)

Drop `Fee`; fix waiver / refund / capability models; add policy
resolution + waitlist as sections 8–9. Keeps the file accurate without
ballooning past one sitting.
