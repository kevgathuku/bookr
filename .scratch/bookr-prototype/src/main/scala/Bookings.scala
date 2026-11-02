package bookr

import java.time.{Instant, LocalDate, ZoneOffset}

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
  case LateAllowed(at: Instant) // policy permits it
  case LatePenalised(at: Instant, how: Enforcement)
  case LateWaived(
      at: Instant,
      waiver: Waiver
  ) // reason rides with the grant: no reason, no waiver

// ---------------------------------------------------------------------------
// 5. Booking status that carries its own cancellation data
//    With status as a bare string, a "cancelled" booking can exist with no
//    record, or a "booked" one with a record. Here a cancellation exists exactly when the status is Cancelled.
// ---------------------------------------------------------------------------
// WAITLISTED rows queue with no seat and zero spend; spend happens on
// promotion, never on join — so Waitlisted carries no money. The late split
// mirrors was_late: LateCancelled always carries a late outcome, so a
// "late" status holding an on-time cancellation cannot be built.
type LateOnly = Cancellation.LateAllowed | Cancellation.LatePenalised |
  Cancellation.LateWaived

enum BookingStatus:
  case Booked
  case Waitlisted
  // Promoted but unconfirmed: the seat is reserved, nothing is spent, and
  // a deadline applies. Distinct from Booked: an unclaimed seat is not a
  // claimed one (notably at the door, which must now decide explicitly).
  case Held(until: Instant)
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

def isActive(status: BookingStatus): Boolean = status match
  case BookingStatus.Booked | BookingStatus.Waitlisted |
      BookingStatus.Held(_) =>
    true
  case _ => false

// Booking creation: the spend site. Monthly never spends; packs and comped
// balances spend exactly the session's credit cost, failing when short —
// the Either carries no membership on failure, so a refused booking cannot
// half-spend. Duplicates are refused over active statuses only, mirroring
// the partial unique key (a cancelled prior booking frees the natural key,
// which is what makes retries idempotent instead of double bookings).
def book(
    id: BookingId,
    session: Session,
    membership: Membership,
    member: UserId,
    existing: List[Booking],
    now: Instant,
    log: Ledger,
    trail: Trail
): Either[String, (Booking, Membership, Ledger, Trail)] =
  for
    open <- requireOpen(session, now)
    _ <- Either.cond(
      membership.user == member,
      (),
      "membership belongs to another user"
    )
    _ <- Either.cond(
      !existing.exists(b =>
        b.session == session.id && b.member == member && isActive(b.status)
      ),
      (),
      "duplicate booking"
    )
    _ <- Either.cond(
      membership.isActiveOn(LocalDate.ofInstant(now, ZoneOffset.UTC)),
      (),
      "membership is not currently valid"
    )
    paid <- membership.debit(session.creditCost)
  yield paid match
    case (stamp, debited) =>
      val booked = Booking(
        id,
        member,
        session.id,
        membership.id,
        BookingStatus.Booked,
        stamp
      )
      // Every booking writes one row, even with zero delta: the value
      // consumed is visible regardless of membership kind. A free session
      // writes a row carrying neither money nor value - it still marks the
      // booking, so free sessions stay visible for attendance analysis.
      val entry =
        LedgerEntry(
          id,
          membership.id,
          -stamp.credits,
          session.creditCost,
          LedgerReason.Spend,
          now
        )
      val transition = Transition(id, None, BookingStatus.Booked, now)
      (booked, debited, log.post(entry), trail.post(transition))

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

// A membership pins a user to a plan for a date window. The constructor
// enforces the entitlement must match the plan kind — monthly
// never spends, credit packs and gratis complimentary plans both spend
// down a balance.
// Booking on an expired plan is unbuildable upstream of every spend path.
final case class Membership private (
    id: MembershipId,
    user: UserId,
    plan: PlanKind,
    startsOn: LocalDate,
    endsOn: LocalDate,
    entitlement: Entitlement
):
  // Inclusive both ends, mirroring _validate_membership and the door query.
  def isActiveOn(today: LocalDate): Boolean =
    !today.isBefore(startsOn) && !today.isAfter(endsOn)

  // Credits a refund back. Unlimited ignores it, mirroring debit.
  def credit(amount: Int): Membership = entitlement match
    case Entitlement.Unlimited => this
    case Entitlement.Credits(balance) =>
      copy(entitlement = Entitlement.Credits(balance.add(amount)))

  // Spend the session's cost: monthly never debits, balances fail when
  // short. Lives here (not in book) so copy stays private everywhere.
  def debit(n: Int): Either[String, (Stamp, Membership)] = entitlement match
    case Entitlement.Unlimited => Stamp.of(0).map(s => (s, this))
    case Entitlement.Credits(balance) =>
      for
        rest <- balance.spend(n)
        stamp <- Stamp.of(n)
      yield (stamp, copy(entitlement = Entitlement.Credits(rest)))

object Membership:
  def of(
      id: MembershipId,
      user: UserId,
      plan: PlanKind,
      startsOn: LocalDate,
      endsOn: LocalDate,
      entitlement: Entitlement
  ): Either[String, Membership] =
    if endsOn.isBefore(startsOn) then Left("end date is before start date")
    else
      (plan, entitlement) match
        case (PlanKind.Monthly, Entitlement.Unlimited) =>
          Right(new Membership(id, user, plan, startsOn, endsOn, entitlement))
        case (
              PlanKind.CreditPack | PlanKind.Complimentary,
              Entitlement.Credits(_)
            ) =>
          Right(new Membership(id, user, plan, startsOn, endsOn, entitlement))
        case _ => Left("plan and entitlement disagree")
