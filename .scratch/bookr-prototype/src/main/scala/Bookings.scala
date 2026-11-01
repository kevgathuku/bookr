package bookr

import java.time.Instant

import Types.*

// ---------------------------------------------------------------------------
// 4. Cancellation outcomes as distinct cases
//    A bool for late + a bool for waived + a nullable waived-by + a string
//    for what was applied: contradictory combinations are possible, such as waived=True with waived_by=NULL. Here each case holds exactly
//    the data it needs, and no more.
// ---------------------------------------------------------------------------
// A waiver is authority plus justification, inseparable: reason-less waivers
// are rejected, so the constructor demands both. (Standing — waiving a
// staff-decision cancel, where no penalty exists, raises InvalidWaiver —
// needs the booking record, which this sketch doesn't model.)
final case class Waiver(grant: WaiverAuthority.Grant, reason: Reason)

enum Cancellation:
  case OnTime(at: Instant)
  case LateAllowed(at: Instant)                         // policy permits it
  case LatePenalised(at: Instant, how: Enforcement)
  case LateWaived(at: Instant, waiver: Waiver) // reason rides with the grant: no reason, no waiver

// ---------------------------------------------------------------------------
// 5. Booking status that carries its own cancellation data
//    With status as a bare string, a "cancelled" booking can exist with no
//    record, or a "booked" one with a record. Here a cancellation exists exactly when the status is Cancelled.
// ---------------------------------------------------------------------------
// WAITLISTED rows queue with no seat and zero spend; spend happens on
// promotion, never on join — so Waitlisted carries no money. The late split
// mirrors was_late: LateCancelled always carries a late outcome, so a
// "late" status holding an on-time cancellation cannot be built.
type LateOnly = Cancellation.LateAllowed | Cancellation.LatePenalised | Cancellation.LateWaived

enum BookingStatus:
  case Booked
  case Waitlisted
  // Cancelled pairs with a non-penalised outcome. Member cancels land here
  // only when on-time; a late-but-unpenalised cancel (staff decision,
  // provider session-cancel) carries LateAllowed with the cause explaining
  // why — the constructor functions pair those two, never the member path.
  case Cancelled(how: Cancellation.OnTime | Cancellation.LateAllowed)
  case LateCancelled(how: LateOnly)
  case Attended
  case NoShow

// The booking itself: member, session, and membership are IDs (their
// entities land in phase 2, and startsAt still arrives loose with them).
// Status and the spent stamp live here, which lets cancel paths return the
// flipped booking alongside its record.
final case class Booking(
  id: BookingId,
  member: UserId,
  session: SessionId,
  membership: MembershipId,
  status: BookingStatus,
  spent: Stamp
)

// Booking debits this many credits at booking time (the offering's
// credit_cost, possibly > 1). Refunds return exactly the stamp — never a
// hardcoded 1 — and LoseCredit forfeits it.
final case class Stamp private (credits: Int)

object Stamp:
  def of(credits: Int): Either[String, Stamp] =
    if credits < 0 then Left("stamp must not be negative")
    else Right(new Stamp(credits))

// ---------------------------------------------------------------------------
// 6. Entitlements: credits exist only for plans that use credits
//    A credits counter on every membership, with "unlimited" plans just
//    ignoring it. Here only credit plans carry a balance.
//    Balances below zero are unbuildable: CreditBalance.of refuses them.
// ---------------------------------------------------------------------------
enum Entitlement:
  case Unlimited
  case Credits(balance: CreditBalance)
