package bookr

import java.time.{Duration, Instant}

// ---------------------------------------------------------------------------
// 11. Waitlist / promotion / hold lifecycle.
//    Joining stamps zero — spend happens at promotion, never at join, even
//    if the passed booking carries a stamp. Promotion re-checks payment
//    against a freshly supplied membership: a head that cannot pay stays
//    queued and the seat stays open. Holds ride on the BOOKED row with an
//    expiry; the sweep releases them and reports the stamps to credit back.
// ---------------------------------------------------------------------------

val HoldWindow: Duration = Duration.ofMinutes(60)

def joinWaitlist(queue: List[Booking], booking: Booking): List[Booking] =
  queue :+ booking.copy(
    status = BookingStatus.Waitlisted,
    spent = Stamp.of(0).toOption.get,
    holdUntil = None
  )

def promoteHead(
    queue: List[Booking],
    membership: Membership,
    price: Int,
    now: Instant,
    openSeats: Int,
    holdFor: Duration = HoldWindow
): (List[Booking], Option[(Booking, Membership)]) =
  if openSeats <= 0 then (queue, None)
  else
    queue match
      case head :: tail if head.status == BookingStatus.Waitlisted =>
        membership.debit(price) match
          // Cannot pay now: stays queued, seat stays open.
          case Left(_) => (queue, None)
          case Right((stamp, debited)) =>
            val seated = head.copy(
              status = BookingStatus.Booked,
              spent = stamp,
              holdUntil = Some(now.plus(holdFor)),
              membership = membership.id
            )
            (seated :: tail, Some((seated, debited)))
      // Head-only: a non-waiting head means no promotion.
      case _ => (queue, None)

def sweepHolds(
    queue: List[Booking],
    now: Instant
): (List[Booking], List[(BookingId, Int)]) =
  val swept = queue.map { b =>
    b.holdUntil match
      case Some(expires)
          if b.status == BookingStatus.Booked && !expires.isAfter(now) =>
        // Expiry is not a late cancel: OnTime here means "no late outcome
        // recorded", and the full stamp comes back like any unpenalised cancel.
        (
          b.copy(
            status = BookingStatus.Cancelled(Cancellation.OnTime(now)),
            holdUntil = None
          ),
          Some((b.id, b.spent.credits))
        )
      case _ => (b, None)
  }
  (swept.map(_._1), swept.collect { case (_, Some(refund)) => refund })
