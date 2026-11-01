# InvalidStates.scala — accuracy audit (2026-11-01)

Review of `.scratch/prototype/InvalidStates.scala` against the current
domain. Verdict: sections 1, 4 (partly), 5 (partly), 7 capture real
weaknesses — but section 3 models a feature that does not exist, and the
largest invalid-state machinery in the domain is unmodeled.

## Inaccuracies (prototype contradicts the code)

1. **`Enforcement.Fee` does not exist.** ✅ Resolved (2026-11-01) — Fee
   kept as the deferred `bookr-55d` sketch, now fenced: `Policy.of` refuses
   Fee on group sessions (fee ⇔ private late cancels only, per the recorded
   scope decision), and the constructor notes the path is deferred behind
   a payments provider that does not exist yet.

2. **`CancelWindow` positivity contradicts the baseline.**
   `late_cancel_hours` is a `PositiveIntegerField` (i.e. `>= 0`), and
   `booking/policies.py` auto-creates the baseline with
   `late_cancel_hours=0, enforcement=NONE`. Zero is legal by design ("no
   late window"); only negatives are blocked, by field type, not
   `clean()`. The smart constructor as specified rejects the domain's own
   default policy.

3. **`decide` invents a waive path the domain forbids.**
   `(Some(who), _)` → `LateWaived` even under `NoPenalty`, with no reason.
   Actual (`booking/cancellations.py`): waiving needs a capability check
   *and* a mandatory reason; waiving with nothing to waive raises
   `InvalidWaiver`; retroactive `waive_record` compensates **only**
   `LOSE_CREDIT` forfeits (strikes forgive inline, fees/monthly/comped
   seats have nothing to compensate). The uniform `LateWaived` erases the
   distinctions `InvalidWaiver` enforces.

4. **Refund of exactly 1 is wrong.** ✅ Resolved (2026-11-01)
   The prototype now carries `Stamp(credits)` (the debited `credits_spent`):
   `refundAmount` returns the stamp, `0` under `LoseCredit`, and `refund`
   adds that amount.

5. **Capabilities don't match `organizations/capabilities.py` (ADR-0007).**
   ✅ Resolved (2026-11-01) — the enum now mirrors the real predicates
   (`OperateDesk / ManageStaff / WaivePenalty / OperateDoor / EnterFree`,
   including the entry/operator split), Teacher holds both door
   capabilities, and the invented billing/policy/cancel-any names are gone.
   Policy edits stay admin-side behind staff gates: no named capability
   there, none here.

6. **Records are mandatory, not optional.**
   Section 5 claims a cancelled booking "may or may not" have a record.
   Every cancel path (member cancel, provider session-cancel, no-show)
   writes exactly one `CancellationRecord`. The real invariant is
   one-record-per-cancel-event plus the `Cause` enum
   (`MEMBER_CANCEL / STAFF_DECISION / SESSION_CANCELLED / NO_SHOW`),
   including the staff-on-behalf path (full refund, status `CANCELLED`).

7. **`BookingStatus` is missing 2 of 6 states.** ✅ Resolved (2026-11-01)
   `Waitlisted` added (no seat, zero spend); the late split is now
   type-enforced — `LateCancelled` takes only `LateOnly` (Allowed /
   Penalised / Waived), `Cancelled` only `OnTime`. Compiler-verified:
   `LateCancelled(OnTime(...))` fails with `Required: LateOnly`.

8. **Own medicine not taken.**
   `Credits(remaining: Int)` and `Money(cents: Long)` admit negatives.
   `Scope.OrgWide` never checks the venue belongs to the org.

## Missing (ranked)

1. **Policy resolution** — nullable `venue / class_category / plan_type` +
   `priority` + auto-baseline makes `resolve_policy` *total*. The
   codebase's best make-invalid-states-unrepresentable example,
   unmodeled.
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
