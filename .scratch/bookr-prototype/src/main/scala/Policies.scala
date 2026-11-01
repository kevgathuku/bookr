package bookr

import Types.*

// ---------------------------------------------------------------------------
// 3. Data that only exists when it makes sense
//    A nullable amount plus a "required when enforcement is 'fee'" rule can
//    disagree — and a fee on a backfillable group seat misprices the loss.
//    Here only Fee carries an amount, and only a private-scoped policy can carry Fee.
//    Amounts below zero are unbuildable: Money.of refuses them.
// ---------------------------------------------------------------------------
enum Enforcement:
  case NoPenalty // lateness allowed (still logged)
  case Strike
  case LoseCredit // forfeits the booking stamp; the amount rides with Stamp, never here
  case Fee(amount: Money) // cannot exist without an amount

// Enforcement.Fee()              // does not compile: amount is missing

final case class Policy private (
    venue: Option[VenueId],
    category: Option[SessionKind],
    plan: Option[PlanKind],
    priority: Int,
    window: CancelWindow,
    enforcement: Enforcement
):

  def specificity: Int = List(venue, category, plan).count(_.isDefined)
  def rank: (Int, Int) = (specificity, priority)

  def matches(
      atVenue: VenueId,
      ofCategory: SessionKind,
      ofPlan: PlanKind
  ): Boolean =
    (venue.isEmpty || venue.contains(atVenue)) &&
      (category.isEmpty || category.contains(ofCategory)) &&
      (plan.isEmpty || plan.contains(ofPlan))

// Group seats backfill from the waitlist; private hours die empty. Fee is
// the price of unbackfillable time, so a fee rule must pin the private
// category scope — an unscoped fee would leak onto group sessions.
// (Deferred in the reportedly-modelled system: no payments provider yet —
// see bookr-55d. The constructor already encodes the decided scope:
// fee ⇔ private late cancels only.)
enum SessionKind:
  case Group, Private, Workshop

enum PlanKind:
  case Monthly, CreditPack, Complimentary

object Policy:
  def of(
      venue: Option[VenueId] = None,
      category: Option[SessionKind] = None,
      plan: Option[PlanKind] = None,
      priority: Int = 0,
      window: CancelWindow,
      enforcement: Enforcement
  ): Either[String, Policy] =
    (category, enforcement) match
      case (_, Enforcement.Fee(_)) if category != Some(SessionKind.Private) =>
        Left("fee enforcement requires a private category scope")
      case _ =>
        Right(new Policy(venue, category, plan, priority, window, enforcement))

  // The totality guarantee: an all-null rule matches every context, so
  // prepending it makes the candidate list non-empty by construction and
  // maxBy cannot fail. Mirrors _ensure_baseline (priority -1, window 0).
  // Policies passed to resolve are one org's rules; the baseline belongs
  // to them the way the ensured row belongs to its org.
  // .get is safe: NoPenalty passes every check in of. Routing the baseline
  // through the smart constructor means future validations apply to it too.
  def baseline: Policy =
    Policy
      .of(
        window = CancelWindow.zero,
        enforcement = Enforcement.NoPenalty,
        priority = -1
      )
      .toOption
      .get

  def resolve(
      policies: List[Policy],
      venue: VenueId,
      category: SessionKind,
      plan: PlanKind
  ): Policy =
    val candidates = Policy.baseline :: policies
    candidates.filter(_.matches(venue, category, plan)).maxBy(_.rank)
