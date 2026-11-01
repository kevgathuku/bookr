//> using scala 3.3.4
//
// Run with scala-cli:   scala-cli run InvalidStates.scala
//
// Standard library only. Each section replaces a place where the Django models
// relied on a nullable column, a string, or a clean() check with a type the
// compiler enforces.

import java.time.{Duration, Instant}

// ---------------------------------------------------------------------------
// 1. Separate ID types
//    Django: every FK is "an int". Passing a venue id where an org id is
//    expected is a runtime bug. Here it is a compile error.
// ---------------------------------------------------------------------------
final case class OrgId(value: Long) extends AnyVal
final case class VenueId(value: Long) extends AnyVal
final case class UserId(value: Long) extends AnyVal

def venueTimezone(venue: VenueId): String = "Europe/Madrid" // stub

// venueTimezone(OrgId(1))        // does not compile: OrgId is not a VenueId

// ---------------------------------------------------------------------------
// 2. A value that can only be built valid (smart constructor)
//    Django: late_cancel_window is "any duration", including 0 or negative,
//    unless clean() catches it. Here there is no way to hold a bad one.
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
//    Django: fee_amount is nullable on every policy, and clean() has to check
//    "required when enforcement is 'fee'". Here only Fee carries an amount.
// ---------------------------------------------------------------------------
final case class Money(cents: Long)

enum Enforcement:
  case NoPenalty            // lateness allowed (still logged)
  case Strike
  case LoseCredit
  case Fee(amount: Money)   // cannot exist without an amount

// Enforcement.Fee()              // does not compile: amount is missing

final case class Policy(window: CancelWindow, enforcement: Enforcement)

// ---------------------------------------------------------------------------
// 4. Cancellation outcomes as distinct cases
//    Django: was_late (bool) + penalty_waived (bool) + waived_by (nullable FK)
//    + enforcement_applied (string). Contradictory combinations are possible,
//    such as waived=True with waived_by=NULL. Here each case holds exactly
//    the data it needs, and no more.
// ---------------------------------------------------------------------------
enum Cancellation:
  case OnTime(at: Instant)
  case LateAllowed(at: Instant)                         // policy permits it
  case LatePenalised(at: Instant, how: Enforcement)
  case LateWaived(at: Instant, waivedBy: UserId)        // waivedBy always present

// ---------------------------------------------------------------------------
// 5. Booking status that carries its own cancellation data
//    Django: status is a string, and a CancellationRecord row may or may not
//    exist (a "cancelled" booking with no record, or a "booked" one with a
//    record). Here a cancellation exists exactly when the status is Cancelled.
// ---------------------------------------------------------------------------
enum BookingStatus:
  case Booked
  case Cancelled(how: Cancellation)
  case Attended
  case NoShow

// ---------------------------------------------------------------------------
// 6. Entitlements: credits exist only for plans that use credits
//    Django: credits_remaining exists on every membership, and "unlimited"
//    plans just ignore it.
// ---------------------------------------------------------------------------
enum Entitlement:
  case Unlimited
  case Credits(remaining: Int)

// ---------------------------------------------------------------------------
// 7. Role scope instead of a nullable venue
//    Django: venue=None means "org-wide" by convention only.
// ---------------------------------------------------------------------------
enum Scope:
  case OrgWide(org: OrgId)
  case AtVenue(venue: VenueId)

enum Role:
  case Owner, Manager, Frontdesk, Teacher, Member

enum Capability:
  case ManageBilling, ManageStaff, EditPolicies, WaiveLateFee, CancelAnyBooking

final case class RoleAssignment(user: UserId, role: Role, scope: Scope)

def appliesAt(scope: Scope, org: OrgId, venue: VenueId): Boolean = scope match
  case Scope.OrgWide(o)    => o == org
  case Scope.AtVenue(v)    => v == venue

// This match has no catch-all case. If you add a Role (say, Assistant) and
// forget it here, the compiler warns about a non-exhaustive match. Make
// warnings fatal (-Xfatal-warnings in Scala 3.3) and it becomes a build
// failure. In Django, a forgotten role string silently gets no capabilities.
def capabilities(role: Role): Set[Capability] = role match
  case Role.Owner =>
    Set(Capability.ManageBilling, Capability.ManageStaff, Capability.EditPolicies,
        Capability.WaiveLateFee, Capability.CancelAnyBooking)
  case Role.Manager =>
    Set(Capability.ManageStaff, Capability.EditPolicies,
        Capability.WaiveLateFee, Capability.CancelAnyBooking)
  case Role.Frontdesk =>
    Set(Capability.WaiveLateFee, Capability.CancelAnyBooking)
  case Role.Teacher => Set.empty
  case Role.Member  => Set.empty

def can(assignments: List[RoleAssignment], user: UserId, org: OrgId, venue: VenueId,
        cap: Capability): Boolean =
  assignments.exists { a =>
    a.user == user && appliesAt(a.scope, org, venue) && capabilities(a.role).contains(cap)
  }

// ---------------------------------------------------------------------------
// The decision itself: a pure function, no database, no clock, no side effects.
// ---------------------------------------------------------------------------
def decide(policy: Policy, classStart: Instant, now: Instant,
           waivedBy: Option[UserId]): Cancellation =
  val cutoff = classStart.minus(policy.window.duration)
  if !now.isAfter(cutoff) then Cancellation.OnTime(now)
  else
    (waivedBy, policy.enforcement) match
      case (Some(who), _)                 => Cancellation.LateWaived(now, who)
      case (None, Enforcement.NoPenalty)  => Cancellation.LateAllowed(now)
      case (None, other)                  => Cancellation.LatePenalised(now, other)

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
  val policy = Policy(window, Enforcement.Fee(Money(1500)))
  val start  = Instant.parse("2026-11-02T18:00:00Z")

  val late = decide(policy, start, Instant.parse("2026-11-02T10:00:00Z"), waivedBy = None)
  println(s"late cancel under fee policy -> $late")
  println(s"fee owed on that cancellation -> ${lateFee(late)}")
  val spent = Stamp(credits = 2) // credit_cost > 1: the stamp flows back
  val back = refundAmount(late, spent)
  println(s"booking spent ${spent.credits} credits, refunded $back" +
    " (a fee does not take the credits)")
  println(s"balance Credits(3) + $back refunded = " +
    refund(Entitlement.Credits(3), back))

  val waived = decide(policy, start, Instant.parse("2026-11-02T10:00:00Z"), Some(UserId(7)))
  println(s"same cancel, waived by staff -> $waived")
  println(s"fee owed after waiver -> ${lateFee(waived)}")

  println(s"zero-length window rejected -> ${CancelWindow.of(Duration.ZERO)}")

  val assignments = List(RoleAssignment(UserId(7), Role.Frontdesk, Scope.AtVenue(VenueId(2))))
  println(s"frontdesk of venue 2 waives at venue 2 -> " +
    can(assignments, UserId(7), OrgId(1), VenueId(2), Capability.WaiveLateFee))
  println(s"frontdesk of venue 2 waives at venue 3 -> " +
    can(assignments, UserId(7), OrgId(1), VenueId(3), Capability.WaiveLateFee))
