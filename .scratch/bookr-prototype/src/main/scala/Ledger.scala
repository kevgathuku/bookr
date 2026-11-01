package bookr

import java.time.Instant

// Append-only credit journal: every credit movement writes exactly one row.
// The log only grows - entries are never edited or deleted, so any balance
// can be recomputed from history. Use balanceOf to check, post to append.
enum LedgerReason:
  case Spend // booking / confirm charge: delta is negative
  case Refund // late-cancel / provider-cancel / sweep-adjacent returns
  case Compensation // retroactive waiver payout

final case class LedgerEntry(
    booking: BookingId,
    membership: MembershipId,
    delta: Int,
    reason: LedgerReason,
    at: Instant
)

final case class Ledger private (entries: List[LedgerEntry]):
  def post(entry: LedgerEntry): Ledger = Ledger(entry :: entries)

  def balanceOf(membership: MembershipId): Int =
    entries.filter(_.membership == membership).map(_.delta).sum

object Ledger:
  val empty: Ledger = Ledger(Nil)
