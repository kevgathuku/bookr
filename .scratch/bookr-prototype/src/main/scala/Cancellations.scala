package bookr

import java.time.Instant

import Types.*

// ---------------------------------------------------------------------------
// The decision itself: a pure function, no database, no clock, no side effects.
// ---------------------------------------------------------------------------
// Callers pass IDs, not existence proofs: a VenueId builds with no row
// behind it. What it always carries is its org, so scope checks read the
// venue's org off the ID instead of trusting the caller's word. Existence
// stays the outer layer's job; with no grant, venue goes unused.
def decide(
    policy: Policy,
    classStart: Instant,
    now: Instant,
    venue: VenueId,
    waiver: Option[Waiver]
): Cancellation =
  val cutoff = classStart.minus(policy.window.duration)
  if !now.isAfter(cutoff) then Cancellation.OnTime(now)
  else
    waiver match
      // A grant minted for another scope is not a waiver here: fail closed
      // toward the policy outcome: deny by default.
      case Some(w) if appliesAt(w.grant.scope, venue) =>
        Cancellation.LateWaived(now, w)
      case _ =>
        policy.enforcement match
          case Enforcement.NoPenalty => Cancellation.LateAllowed(now)
          case other                 => Cancellation.LatePenalised(now, other)

// Pattern matching can reach inside a case. The fee amount is only reachable
// when the enforcement really is a Fee.
def lateFee(c: Cancellation): Option[Money] = c match
  case Cancellation.LatePenalised(_, Enforcement.Fee(amount)) => Some(amount)
  case _                                                      => None

def refundAmount(c: Cancellation, spent: Stamp): Int = c match
  case Cancellation.LatePenalised(_, Enforcement.LoseCredit) => 0
  case _                                                     => spent.credits

def refund(e: Entitlement, amount: Int): Entitlement = (e, amount) match
  case (Entitlement.Unlimited, _)  => Entitlement.Unlimited
  case (Entitlement.Credits(b), a) => Entitlement.Credits(b.add(a))

// ---------------------------------------------------------------------------
// 9. Records are mandatory, not optional.
//    Cancel paths return the flipped booking with exactly one CancellationRecord —
//    the status flip and the record write are one atomic pair. CancellationRecord.of
//    refuses hand-built nonsense: cause must agree with
//    status (NoShow with NoShow, terminal statuses otherwise; Booked and
//    friends never carry records) and the refund cannot exceed the stamp.
//    Retroactive waiver (reassess) compensates only a standing LOSE_CREDIT
//    forfeit; everything else names its refusal, mirroring InvalidWaiver.
// ---------------------------------------------------------------------------
enum Cause:
  case MemberCancel, StaffDecision, SessionCancelled, NoShow

final case class CancellationRecord private (
    booking: BookingId,
    cause: Cause,
    status: BookingStatus,
    refunded: Int,
    spent: Stamp
)

object CancellationRecord:
  def of(
      booking: BookingId,
      cause: Cause,
      status: BookingStatus,
      refunded: Int,
      spent: Stamp
  ): Either[String, CancellationRecord] =
    val causeOk = (cause, status) match
      case (Cause.NoShow, BookingStatus.NoShow) => true
      case (Cause.NoShow, _)                    => false
      case (_, BookingStatus.NoShow)            => false
      case (_, BookingStatus.Cancelled(_) | BookingStatus.LateCancelled(_)) =>
        true
      case _ => false
    if !causeOk then Left("record cause and status disagree")
    else if refunded < 0 || refunded > spent.credits then
      Left("refund exceeds stamp")
    else Right(new CancellationRecord(booking, cause, status, refunded, spent))

// The only ways to make a CancellationRecord. Member cancels derive status from the
// decision; staff and provider cancels never penalise (full stamp refund,
// status CANCELLED even when late — the cause, not the policy, explains
// why); no-shows keep the stamp spent.
def cancelMember(
    policy: Policy,
    venue: VenueId,
    start: Instant,
    now: Instant,
    booking: Booking,
    waiver: Option[Waiver]
): (Booking, CancellationRecord) =
  val cancellation = decide(policy, start, now, venue, waiver)
  val status = cancellation match
    case o: Cancellation.OnTime        => BookingStatus.Cancelled(o)
    case l: Cancellation.LateAllowed   => BookingStatus.LateCancelled(l)
    case l: Cancellation.LatePenalised => BookingStatus.LateCancelled(l)
    case l: Cancellation.LateWaived    => BookingStatus.LateCancelled(l)
  val record = CancellationRecord
    .of(
      booking.id,
      Cause.MemberCancel,
      status,
      refundAmount(cancellation, booking.spent),
      booking.spent
    )
    .toOption
    .get
  (booking.copy(status = status), record)

def cancelUnpenalised(
    cause: Cause,
    policy: Policy,
    venue: VenueId,
    start: Instant,
    now: Instant,
    booking: Booking
): (Booking, CancellationRecord) =
  val cutoff = start.minus(policy.window.duration)
  val status =
    if !now.isAfter(cutoff) then
      BookingStatus.Cancelled(Cancellation.OnTime(now))
    else BookingStatus.Cancelled(Cancellation.LateAllowed(now))
  val record = CancellationRecord
    .of(booking.id, cause, status, booking.spent.credits, booking.spent)
    .toOption
    .get
  (booking.copy(status = status), record)

def cancelStaff(
    policy: Policy,
    venue: VenueId,
    start: Instant,
    now: Instant,
    booking: Booking
): (Booking, CancellationRecord) =
  cancelUnpenalised(Cause.StaffDecision, policy, venue, start, now, booking)

def cancelSession(
    policy: Policy,
    venue: VenueId,
    start: Instant,
    now: Instant,
    booking: Booking
): (Booking, CancellationRecord) =
  cancelUnpenalised(Cause.SessionCancelled, policy, venue, start, now, booking)

def markNoShow(booking: Booking): (Booking, CancellationRecord) =
  val record = CancellationRecord
    .of(booking.id, Cause.NoShow, BookingStatus.NoShow, 0, booking.spent)
    .toOption
    .get
  (booking.copy(status = BookingStatus.NoShow), record)

// Retroactive waiver: compensates a standing LOSE_CREDIT forfeit, nothing
// else. The grant is re-verified against the venue here, the way the write
// transaction re-checks — a stored record is no fresher than a passed ID.
def reassess(
    record: CancellationRecord,
    venue: VenueId,
    waiver: Waiver
): Either[String, Int] =
  if !appliesAt(waiver.grant.scope, venue) then
    Left("waiver grant covers another scope")
  else
    record match
      case CancellationRecord(
            _,
            Cause.MemberCancel,
            BookingStatus.LateCancelled(
              Cancellation.LatePenalised(_, Enforcement.LoseCredit)
            ),
            0,
            spent
          ) if spent.credits > 0 =>
        Right(spent.credits)
      case CancellationRecord(
            _,
            Cause.MemberCancel,
            BookingStatus.LateCancelled(
              Cancellation.LatePenalised(_, Enforcement.LoseCredit)
            ),
            _,
            _
          ) =>
        Left("no standing forfeit to waive")
      case _ =>
        Left("record carries no compensable forfeit")
