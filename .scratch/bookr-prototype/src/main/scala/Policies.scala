package bookr

import Types.*

// ---------------------------------------------------------------------------
// 3. Data that only exists when it makes sense
//    A nullable amount plus a "required when enforcement is 'fee'" rule can
//    disagree — and a fee on a backfillable group seat misprices the loss.
//    Here only Fee carries an amount, and only a private policy can carry Fee.
//    Amounts below zero are unbuildable: Money.of refuses them.
// ---------------------------------------------------------------------------
enum Enforcement:
  case NoPenalty            // lateness allowed (still logged)
  case Strike
  case LoseCredit // forfeits the booking stamp; the amount rides with Stamp, never here
  case Fee(amount: Money)   // cannot exist without an amount

// Enforcement.Fee()              // does not compile: amount is missing

final case class Policy private (kind: SessionKind, window: CancelWindow,
                                 enforcement: Enforcement)

// Group seats backfill from the waitlist; private hours die empty. Fee is
// the price of unbackfillable time, so Policy.of refuses Fee on anything
// but Private. (Deferred in the reportedly-modelled system: no payments
// provider yet — see bookr-55d. The constructor already encodes the
// decided scope: fee ⇔ private late cancels only.)
enum SessionKind:
  case Group, Private

object Policy:
  def of(kind: SessionKind, window: CancelWindow,
         enforcement: Enforcement): Either[String, Policy] =
    (kind, enforcement) match
      case (SessionKind.Group, Enforcement.Fee(_)) =>
        Left("fee enforcement is private-only")
      case _ => Right(new Policy(kind, window, enforcement))
