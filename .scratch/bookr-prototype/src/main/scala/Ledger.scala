package bookr

import java.time.Instant

// Append-only value journal: every spend or confirm writes exactly one
// row, snapshotting the value consumed at event time (not the live price).
// The log only grows - entries are never edited or deleted, so both money
// and value can be recomputed from history. Use balanceOf to check,
// valueOf to analyse consumption, post to append.
//    Every spend or confirm has exactly one row, always - including a
//    free session, whose row carries neither money nor value but still
//    marks the event, so free bookings stay visible for attendance.
enum LedgerReason:
  case Spend // booking / confirm charge: delta is negative
  case Refund // late-cancel / provider-cancel / sweep-adjacent returns
  case Compensation // retroactive waiver payout

final case class LedgerEntry(
    booking: BookingId,
    membership: MembershipId,
    delta: Int,
    value: Int,
    reason: LedgerReason,
    at: Instant
)

final case class Ledger private (entries: List[LedgerEntry]):
  def post(entry: LedgerEntry): Ledger = Ledger(entry :: entries)

  def balanceOf(membership: MembershipId): Int =
    entries.filter(_.membership == membership).map(_.delta).sum

  def valueOf(membership: MembershipId): Int =
    entries.filter(_.membership == membership).map(_.value).sum

object Ledger:
  val empty: Ledger = Ledger(Nil)
