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

def joinWaitlist(queue: List[Booking], booking: Booking): List[Booking] =
  queue :+ booking.copy(
    status = BookingStatus.Waitlisted,
    spent = Stamp.of(0).toOption.get
  )

// openSeats is caller-computed per trigger (capacity minus active bookings,
// holds included) and never cached: a stale count double-promises one seat.
// Callers must also serialize triggers per session; atomicity lives with
// them, as it does for book()'s natural key.
def promoteHead(
    queue: List[Booking],
    now: Instant,
    openSeats: Int,
    holdFor: Duration = HoldWindow
): (List[Booking], Option[Booking]) =
  if openSeats <= 0 then (queue, None)
  else
    queue match
      // The seated head leaves the queue: the waitlist holds waiters
      // only, so a held seat can never be re-promised from this list.
      case head :: tail if head.status == BookingStatus.Waitlisted =>
        val seated = head.copy(status = BookingStatus.Held(now.plus(holdFor)))
        (tail, Some(seated))
      // Head-only: a non-waiting head means no promotion.
      case _ => (queue, None)

// The spend site moves here from promotion: a promoted seat is an offer,
// not a sale. Charging at confirm removes the charge-then-refund cycle on
// decline - money only ever moves toward a claimed seat.
def confirmHold(
    booking: Booking,
    membership: Membership,
    session: Session,
    now: Instant
): Either[String, (Booking, Membership)] =
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
          (booking.copy(status = BookingStatus.Booked, spent = stamp), debited)
    case _ => Left("no hold to confirm")

// Shared exit for unconfirmed holds: never charged, so never penalised,
// refunded, or waived - released as unclaimed regardless of lateness.
def releaseHold(booking: Booking, now: Instant): (Booking, CancellationRecord) =
  val status = BookingStatus.Cancelled(Cancellation.OnTime(now))
  val record =
    CancellationRecord
      .of(booking.id, Cause.Unclaimed, status, 0, booking.spent)
      .toOption
      .get
  (booking.copy(status = status), record)

def declineHold(
    booking: Booking,
    now: Instant
): Either[String, (Booking, CancellationRecord)] =
  booking.status match
    case BookingStatus.Held(_) => Right(releaseHold(booking, now))
    case _                     => Left("no hold to decline")

def sweepHolds(
    bookings: List[Booking],
    now: Instant
): (List[Booking], List[(Booking, CancellationRecord)]) =
  // Inclusive by design (see boundary test): strict < would trap a
  // hold expiring exactly on a sweep tick until the next run.
  // Released rows leave the list with the seated ones: callers keep
  // terminal bookings in their own store; the queue holds waiters only.
  val (fallen, kept) = bookings.partition {
    case Booking(_, _, _, _, BookingStatus.Held(expires), _) =>
      !expires.isAfter(now)
    case _ => false
  }
  (kept, fallen.map(b => releaseHold(b, now)))
