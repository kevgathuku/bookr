package bookr

import java.time.Instant

// ---------------------------------------------------------------------------
// 12. Audit trail: every status change writes exactly one row. Like Ledger,
// the trail only grows - entries are never edited or deleted, so any
// booking's full path can be replayed from history. Use forBooking to read,
// post to append.
//    `from` is the status the booking held before the event; None means the
//    booking entered the trail here (created, or joined the waitlist for the
//    first time). A rejoin under the same id links to the state it left.
//    The trail records status only - money lives in the Ledger - so a
//    status change writes a row whether or not money moved.
// ---------------------------------------------------------------------------
final case class Transition(
    booking: BookingId,
    from: Option[BookingStatus],
    to: BookingStatus,
    at: Instant
)

final case class Trail private (entries: List[Transition]):
  def post(entry: Transition): Trail = Trail(entry :: entries)

  // Oldest first. post prepends, so reverse before the stable sort:
  // events sharing a timestamp keep the order they were written in.
  def forBooking(id: BookingId): List[Transition] =
    entries.filter(_.booking == id).reverse.sortBy(_.at.toEpochMilli)

object Trail:
  val empty: Trail = Trail(Nil)
