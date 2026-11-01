//> using scala 3.3.4
//
// Run with scala-cli:   scala-cli run InvalidStates.scala
//
// Standard library only. Each section replaces a nullable column, a string,
// or a validation check with a type the compiler enforces.

import java.time.{Duration, Instant}

// ---------------------------------------------------------------------------
// 1. Separate ID types
//    With plain integer IDs, passing a venue id where an org id is
//    expected is a runtime bug. Here it is a compile error.
// ---------------------------------------------------------------------------
final case class OrgId(value: Long) extends AnyVal
final case class VenueId(value: Long) extends AnyVal
final case class UserId(value: Long) extends AnyVal

def venueTimezone(venue: VenueId): String = "Europe/Madrid" // stub

// venueTimezone(OrgId(1))        // does not compile: OrgId is not a VenueId

// ---------------------------------------------------------------------------
// 2. A value that can only be built valid (smart constructor)
//    A raw duration admits 0 or negatives unless every use site checks.
//    Here there is no way to hold a bad one.
// ---------------------------------------------------------------------------
object Types:
  opaque type CancelWindow = Duration

  object CancelWindow:
    def of(d: Duration): Either[String, CancelWindow] =
      if d.isNegative || d.isZero then Left("cancel window must be positive")
      else Right(d)

  extension (w: CancelWindow) def duration: Duration = w

import Types.*

// ---------------------------------------------------------------------------
// 3. Data that only exists when it makes sense
//    A nullable amount plus a "required when enforcement is 'fee'" rule can
//    disagree — and a fee on a backfillable group seat misprices the loss.
//    Here only Fee carries an amount, and only a private policy can carry Fee.
// ---------------------------------------------------------------------------
final case class Money(cents: Long)

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

// ---------------------------------------------------------------------------
// 4. Cancellation outcomes as distinct cases
//    A bool for late + a bool for waived + a nullable waived-by + a string
//    for what was applied: contradictory combinations are possible, such as waived=True with waived_by=NULL. Here each case holds exactly
//    the data it needs, and no more.
// ---------------------------------------------------------------------------
enum Cancellation:
  case OnTime(at: Instant)
  case LateAllowed(at: Instant)                         // policy permits it
  case LatePenalised(at: Instant, how: Enforcement)
  case LateWaived(at: Instant, grant: WaiverAuthority.Grant) // grant always present, and only issuable via authorizeWaiver

// ---------------------------------------------------------------------------
// 5. Booking status that carries its own cancellation data
//    With status as a bare string, a "cancelled" booking can exist with no
//    record, or a "booked" one with a record. Here a cancellation exists exactly when the status is Cancelled.
// ---------------------------------------------------------------------------
// WAITLISTED rows queue with no seat and zero spend; spend happens on
// promotion, never on join — so Waitlisted carries no money. The late split
// mirrors was_late: LateCancelled always carries a late outcome, so a
// "late" status holding an on-time cancellation cannot be built.
type LateOnly = Cancellation.LateAllowed | Cancellation.LatePenalised | Cancellation.LateWaived

enum BookingStatus:
  case Booked
  case Waitlisted
  case Cancelled(how: Cancellation.OnTime)
  case LateCancelled(how: LateOnly)
  case Attended
  case NoShow

// ---------------------------------------------------------------------------
// 6. Entitlements: credits exist only for plans that use credits
//    A credits counter on every membership, with "unlimited" plans just
//    ignoring it. Here only credit plans carry a balance.
// ---------------------------------------------------------------------------
enum Entitlement:
  case Unlimited
  case Credits(remaining: Int)

// ---------------------------------------------------------------------------
// 7. Role scope instead of a nullable venue
//    A nullable venue where None means "org-wide" by convention only.
// ---------------------------------------------------------------------------
enum Scope:
  case OrgWide(org: OrgId)
  case AtVenue(venue: VenueId)

enum Role:
  case Owner, Manager, Frontdesk, Teacher, Member

// desk operation, staff management, waiver, door operation, free entry. 
enum Capability:
  case OperateDesk, ManageStaff, WaivePenalty, OperateDoor, EnterFree

final case class RoleAssignment(user: UserId, role: Role, scope: Scope)

def appliesAt(scope: Scope, org: OrgId, venue: VenueId): Boolean = scope match
  case Scope.OrgWide(o)    => o == org
  case Scope.AtVenue(v)    => v == venue

// This match has no catch-all case. If you add a Role (say, Assistant) and
// forget it here, the compiler warns about a non-exhaustive match. Make
// warnings fatal (-Xfatal-warnings in Scala 3.3) and it becomes a build
// failure. With stringly-typed roles, a forgotten role silently gets no
// capabilities.
def capabilities(role: Role): Set[Capability] = role match
  case Role.Owner =>
    Set(Capability.OperateDesk, Capability.ManageStaff, Capability.WaivePenalty,
        Capability.OperateDoor, Capability.EnterFree)
  case Role.Manager =>
    Set(Capability.OperateDesk, Capability.ManageStaff, Capability.WaivePenalty,
        Capability.OperateDoor, Capability.EnterFree)
  case Role.Frontdesk =>
    Set(Capability.OperateDesk, Capability.WaivePenalty,
        Capability.OperateDoor, Capability.EnterFree)
  case Role.Teacher => Set(Capability.OperateDoor, Capability.EnterFree)
  case Role.Member  => Set.empty

def can(assignments: List[RoleAssignment], user: UserId, org: OrgId, venue: VenueId,
        cap: Capability): Boolean =
  assignments.exists { a =>
    a.user == user && appliesAt(a.scope, org, venue) && capabilities(a.role).contains(cap)
  }

// Entry privilege vs operator authority: identical today, separate so they
// can diverge without touching gates.
def canOperateDoor(assignments: List[RoleAssignment], user: UserId, org: OrgId,
                   venue: VenueId): Boolean =
  can(assignments, user, org, venue, Capability.OperateDoor)

def isDutyStaff(assignments: List[RoleAssignment], user: UserId, org: OrgId,
                venue: VenueId): Boolean =
  can(assignments, user, org, venue, Capability.EnterFree)

// ---------------------------------------------------------------------------
// 8. Authority as a value, not a prayer.
//    LateWaived demands a Grant, and the only way to mint one is authorize,
//    which runs the capability check. The grant carries the scope it was
//    checked against, and decide re-verifies it: a grant is proof of a
//    check, not a substitute for one. (Residual TOCTOU — rights revoked
//    between authorize and decide — is why the write path re-checks inside
//    its transaction; types move the check earlier, they don't remove it.)
// ---------------------------------------------------------------------------
object WaiverAuthority:
  opaque type Grant = (UserId, Scope)

  def authorize(user: UserId, assignments: List[RoleAssignment],
                org: OrgId, venue: VenueId): Option[Grant] =
    if can(assignments, user, org, venue, Capability.WaivePenalty) then
      Some((user, Scope.AtVenue(venue)))
    else None

  extension (g: Grant)
    def user: UserId = g._1
    def scope: Scope = g._2

// ---------------------------------------------------------------------------
// The decision itself: a pure function, no database, no clock, no side effects.
// ---------------------------------------------------------------------------
// Callers pass IDs, not existence proofs: OrgId(1) builds with no row
// behind it, and nothing in here validates it. Existence is the outer
// layer's job (the outer layer rejects unknown IDs before decide ever runs);
// in here IDs are only compared for scope match. With no grant, org/venue go
// unused — the pure core assumes the boundary already proved them.
def decide(policy: Policy, classStart: Instant, now: Instant,
           org: OrgId, venue: VenueId,
           grant: Option[WaiverAuthority.Grant]): Cancellation =
  val cutoff = classStart.minus(policy.window.duration)
  if !now.isAfter(cutoff) then Cancellation.OnTime(now)
  else grant match
    // A grant minted for another scope is not a waiver here: fail closed
    // toward the policy outcome: deny by default.
    case Some(g) if appliesAt(g.scope, org, venue) =>
      Cancellation.LateWaived(now, g)
    case _ => policy.enforcement match
      case Enforcement.NoPenalty => Cancellation.LateAllowed(now)
      case other                 => Cancellation.LatePenalised(now, other)

// Pattern matching can reach inside a case. The fee amount is only reachable
// when the enforcement really is a Fee.
def lateFee(c: Cancellation): Option[Money] = c match
  case Cancellation.LatePenalised(_, Enforcement.Fee(amount)) => Some(amount)
  case _                                                      => None

// Booking debits this many credits at booking time (the offering's
// credit_cost, possibly > 1). Refunds return exactly the stamp — never a
// hardcoded 1 — and LoseCredit forfeits it.
final case class Stamp(credits: Int)

def refundAmount(c: Cancellation, spent: Stamp): Int = c match
  case Cancellation.LatePenalised(_, Enforcement.LoseCredit) => 0
  case _                                                      => spent.credits

def refund(e: Entitlement, amount: Int): Entitlement = (e, amount) match
  case (Entitlement.Unlimited, _)  => Entitlement.Unlimited
  case (Entitlement.Credits(n), a) => Entitlement.Credits(n + a)

// ---------------------------------------------------------------------------
@main def demo(): Unit =
  val window = CancelWindow.of(Duration.ofHours(12)).toOption.get
  val policy = Policy.of(SessionKind.Private, window, Enforcement.Fee(Money(1500))).toOption.get
  println(Policy.of(SessionKind.Group, window, Enforcement.Fee(Money(1500)))) // Left: fee is private-only
  val start  = Instant.parse("2026-11-02T18:00:00Z")

  val late = decide(policy, start, Instant.parse("2026-11-02T10:00:00Z"), OrgId(1), VenueId(2), None)
  println(s"late cancel under fee policy -> $late")
  println(s"fee owed on that cancellation -> ${lateFee(late)}")
  val spent = Stamp(credits = 2) // credit_cost > 1: the stamp flows back
  val back = refundAmount(late, spent)
  println(s"booking spent ${spent.credits} credits, refunded $back" +
    " (a fee does not take the credits)")
  println(s"balance Credits(3) + $back refunded = " +
    refund(Entitlement.Credits(3), back))

  val assignments = List(RoleAssignment(UserId(7), Role.Frontdesk, Scope.AtVenue(VenueId(2))))

  val grant = WaiverAuthority.authorize(UserId(7), assignments, OrgId(1), VenueId(2))
  println(s"waiver grant for frontdesk -> $grant")
  val memberGrant = WaiverAuthority.authorize(UserId(9), assignments, OrgId(1), VenueId(2))
  println(s"waiver grant for plain member -> $memberGrant") // None: no waive rights

  val waived = decide(policy, start, Instant.parse("2026-11-02T10:00:00Z"), OrgId(1), VenueId(2), grant)
  println(s"same cancel, waived by staff -> $waived")
  println(s"fee owed after waiver -> ${lateFee(waived)}")

  println(s"zero-length window rejected -> ${CancelWindow.of(Duration.ZERO)}")

  println(s"frontdesk of venue 2 waives at venue 2 -> " +
    can(assignments, UserId(7), OrgId(1), VenueId(2), Capability.WaivePenalty))
  println(s"frontdesk of venue 2 waives at venue 3 -> " +
    can(assignments, UserId(7), OrgId(1), VenueId(3), Capability.WaivePenalty))
  println(s"frontdesk enters free at venue 2 -> " +
    isDutyStaff(assignments, UserId(7), OrgId(1), VenueId(2)))
  println(s"frontdesk operates door at venue 2 -> " +
    canOperateDoor(assignments, UserId(7), OrgId(1), VenueId(2)))
