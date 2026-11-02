package bookr

import java.time.{Duration, Instant, LocalDate, ZoneOffset}

// ---------------------------------------------------------------------------
// 11. Waitlist / promotion / hold lifecycle.
//    Joining stamps zero - spend happens at confirm, never at join and never
//    at promotion, even if the passed booking carries a stamp. Promotion
//    seats the head as Held with a deadline and no charge; released and
//    seated bookings leave the queue — it holds waiters only, the way the
//    live query excludes non-waitlisted rows. The sweep reports each
//    release with an Unclaimed record. Held is a case, not a nullable
//    column: a hold exists exactly when the status is Held.
// ---------------------------------------------------------------------------

val HoldWindow: Duration = Duration.ofMinutes(60)

def joinWaitlist(
    queue: List[Booking],
    booking: Booking,
    now: Instant,
    trail: Trail
): (List[Booking], Trail) =
  val waitlisted = booking.copy(
    status = BookingStatus.Waitlisted,
    spent = Stamp.of(0).toOption.get
  )
  // Joining writes a transition even though it moves no money: the trail
  // records status, the ledger records value.
  // The prior status comes from the trail, not from the booking handed in:
  // a rejoin under the same id links to the state it left, and a booking
  // the trail has never seen is one that enters the trail here.
  val from = trail.forBooking(booking.id).lastOption.map(_.to)
  val transition = Transition(booking.id, from, BookingStatus.Waitlisted, now)
  (queue :+ waitlisted, trail.post(transition))

// openSeats is caller-computed per trigger (capacity minus active bookings,
// holds included) and never cached: a stale count double-promises one seat.
// Callers must also serialize triggers per session; atomicity lives with
// them, as it does for book()'s natural key.
def promoteHead(
    queue: List[Booking],
    now: Instant,
    openSeats: Int,
    trail: Trail,
    holdFor: Duration = HoldWindow
): (List[Booking], Option[Booking], Trail) =
  if openSeats <= 0 then (queue, None, trail)
  else
    queue match
      // The seated head leaves the queue: the waitlist holds waiters
      // only, so a held seat can never be re-promised from this list.
      case head :: tail if head.status == BookingStatus.Waitlisted =>
        val held = BookingStatus.Held(now.plus(holdFor))
        val seated = head.copy(status = held)
        val transition =
          Transition(head.id, Some(BookingStatus.Waitlisted), held, now)
        (tail, Some(seated), trail.post(transition))
      // Head-only: a non-waiting head means no promotion.
      case _ => (queue, None, trail)

// The spend site moves here from promotion: a promoted seat is an offer,
// not a sale. Charging at confirm removes the charge-then-refund cycle on
// decline - money only ever moves toward a claimed seat.
def confirmHold(
    booking: Booking,
    membership: Membership,
    session: Session,
    now: Instant,
    log: Ledger,
    trail: Trail
): Either[String, (Booking, Membership, Ledger, Trail)] =
  booking.status match
    case BookingStatus.Held(_) =>
      for
        _ <- requireOpen(session, now)
        _ <- Either.cond(
          booking.spent.credits == 0,
          (),
          "hold is already spent"
        )
        _ <- Either.cond(
          membership.user == booking.member,
          (),
          "membership belongs to another user"
        )
        _ <- Either.cond(
          membership.isActiveOn(LocalDate.ofInstant(now, ZoneOffset.UTC)),
          (),
          "membership is not currently valid"
        )
        paid <- membership.debit(session.creditCost)
      yield paid match
        case (stamp, debited) =>
          val confirmed =
            booking.copy(status = BookingStatus.Booked, spent = stamp)
          // As in book: every confirm writes one row, snapshotting value
          // even when no money moves (unlimited / monthly). A free session
          // writes a row carrying neither - it still marks the claim.
          val entry =
            LedgerEntry(
              booking.id,
              membership.id,
              -stamp.credits,
              session.creditCost,
              LedgerReason.Spend,
              now
            )
          val transition =
            Transition(
              booking.id,
              Some(booking.status),
              BookingStatus.Booked,
              now
            )
          (confirmed, debited, log.post(entry), trail.post(transition))
    case _ => Left("no hold to confirm")

// Shared exit for unconfirmed holds: never charged, so never penalised,
// refunded, or waived - released as unclaimed regardless of lateness.
def releaseHold(
    booking: Booking,
    now: Instant,
    trail: Trail
): (Booking, CancellationRecord, Trail) =
  val status = BookingStatus.Cancelled(Cancellation.OnTime(now))
  val record =
    CancellationRecord
      .of(booking.id, Cause.Unclaimed, status, 0, booking.spent)
      .toOption
      .get
  val transition = Transition(booking.id, Some(booking.status), status, now)
  (booking.copy(status = status), record, trail.post(transition))

def declineHold(
    booking: Booking,
    now: Instant,
    trail: Trail
): Either[String, (Booking, CancellationRecord, Trail)] =
  booking.status match
    case BookingStatus.Held(_) => Right(releaseHold(booking, now, trail))
    case _                     => Left("no hold to decline")

def sweepHolds(
    bookings: List[Booking],
    now: Instant,
    trail: Trail
): (List[Booking], List[(Booking, CancellationRecord)], Trail) =
  // Inclusive by design (see boundary test): strict < would trap a
  // hold expiring exactly on a sweep tick until the next run.
  // Released rows leave the list with the seated ones: callers keep
  // terminal bookings in their own store; the queue holds waiters only.
  val (fallen, kept) = bookings.partition {
    case Booking(_, _, _, _, BookingStatus.Held(expires), _) =>
      !expires.isAfter(now)
    case _ => false
  }
  // Fold, not map: each release posts to the trail the previous one
  // produced, so no transition is lost when several holds expire at once.
  val (released, nextTrail) =
    fallen.foldLeft((List.empty[(Booking, CancellationRecord)], trail)) {
      case ((acc, t), b) =>
        val (booking, record, posted) = releaseHold(b, now, t)
        (acc :+ ((booking, record)), posted)
    }
  (kept, released, nextTrail)
