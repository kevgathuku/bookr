// Run with sbt:   sbt run
//
// Standard library only. Each section replaces a nullable column, a string,
// or a validation check with a type the compiler enforces.

import java.time.{Duration, Instant}

// ---------------------------------------------------------------------------
// 1. Separate ID types
//    With plain integer IDs, passing a venue id where an org id is
//    expected is a runtime bug. Here it is a compile error.
//    Venues carry their org, so scope checks read it instead of trusting the caller.
// ---------------------------------------------------------------------------
final case class OrgId(value: Long) extends AnyVal
final case class VenueId(org: OrgId, value: Long) // a venue always knows its org
final case class UserId(value: Long) extends AnyVal
final case class BookingId(value: Long) extends AnyVal
final case class SessionId(value: Long) extends AnyVal
final case class MembershipId(value: Long) extends AnyVal

def venueTimezone(venue: VenueId): String = "Europe/Madrid" // stub

// venueTimezone(OrgId(1))        // does not compile: OrgId is not a VenueId

// ---------------------------------------------------------------------------
// 2. A value that can only be built valid (smart constructor)
//    A raw duration admits negatives unless every use site checks, while
//    the baseline's zero window must stay buildable. Here negatives are
//    refused and zero passes — the bound is >= 0, matching the field.
// ---------------------------------------------------------------------------
object Types:
  opaque type CancelWindow = Duration

  object CancelWindow:
    def of(d: Duration): Either[String, CancelWindow] =
      if d.isNegative then Left("cancel window must not be negative")
      else Right(d)

  extension (w: CancelWindow) def duration: Duration = w

  opaque type CreditBalance = Int
  object CreditBalance:
    def of(n: Int): Either[String, CreditBalance] =
      if n < 0 then Left("credits must not be negative") else Right(n)
  extension (b: CreditBalance)
    def remaining: Int = b
    def add(n: Int): CreditBalance = b + n

  opaque type Money = Long
  object Money:
    def of(cents: Long): Either[String, Money] =
      if cents < 0 then Left("money must not be negative") else Right(cents)
  extension (m: Money) def cents: Long = m

  opaque type Reason = String
  object Reason:
    def of(s: String): Either[String, Reason] =
      if s.trim.isEmpty then Left("waiver requires a reason") else Right(s)
  extension (r: Reason) def text: String = r

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

// ---------------------------------------------------------------------------
// 4. Cancellation outcomes as distinct cases
//    A bool for late + a bool for waived + a nullable waived-by + a string
//    for what was applied: contradictory combinations are possible, such as waived=True with waived_by=NULL. Here each case holds exactly
//    the data it needs, and no more.
// ---------------------------------------------------------------------------
// A waiver is authority plus justification, inseparable: reason-less waivers
// are rejected, so the constructor demands both. (Standing — waiving a
// staff-decision cancel, where no penalty exists, raises InvalidWaiver —
// needs the booking record, which this sketch doesn't model.)
final case class Waiver(grant: WaiverAuthority.Grant, reason: Reason)

enum Cancellation:
  case OnTime(at: Instant)
  case LateAllowed(at: Instant)                         // policy permits it
  case LatePenalised(at: Instant, how: Enforcement)
  case LateWaived(at: Instant, waiver: Waiver) // reason rides with the grant: no reason, no waiver

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
  // Cancelled pairs with a non-penalised outcome. Member cancels land here
  // only when on-time; a late-but-unpenalised cancel (staff decision,
  // provider session-cancel) carries LateAllowed with the cause explaining
  // why — the constructor functions pair those two, never the member path.
  case Cancelled(how: Cancellation.OnTime | Cancellation.LateAllowed)
  case LateCancelled(how: LateOnly)
  case Attended
  case NoShow

// The booking itself: member, session, and membership are IDs (their
// entities land in phase 2, and startsAt still arrives loose with them).
// Status and the spent stamp live here, which lets cancel paths return the
// flipped booking alongside its record.
final case class Booking(
  id: BookingId,
  member: UserId,
  session: SessionId,
  membership: MembershipId,
  status: BookingStatus,
  spent: Stamp
)

// ---------------------------------------------------------------------------
// 6. Entitlements: credits exist only for plans that use credits
//    A credits counter on every membership, with "unlimited" plans just
//    ignoring it. Here only credit plans carry a balance.
//    Balances below zero are unbuildable: CreditBalance.of refuses them.
// ---------------------------------------------------------------------------
enum Entitlement:
  case Unlimited
  case Credits(balance: CreditBalance)

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

// The venue carries its org, so "org-wide" is checkable: the scope's org
// must equal the venue's own org. A venue from another org never matches.
def appliesAt(scope: Scope, venue: VenueId): Boolean = scope match
  case Scope.OrgWide(o) => o == venue.org
  case Scope.AtVenue(v) => v == venue

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

def can(assignments: List[RoleAssignment], user: UserId, venue: VenueId,
        cap: Capability): Boolean =
  assignments.exists { a =>
    a.user == user && appliesAt(a.scope, venue) && capabilities(a.role).contains(cap)
  }

// Entry privilege vs operator authority: identical today, separate so they
// can diverge without touching gates.
def canOperateDoor(assignments: List[RoleAssignment], user: UserId,
                   venue: VenueId): Boolean =
  can(assignments, user, venue, Capability.OperateDoor)

def isDutyStaff(assignments: List[RoleAssignment], user: UserId,
                venue: VenueId): Boolean =
  can(assignments, user, venue, Capability.EnterFree)

// ---------------------------------------------------------------------------
// 8. Authority as a value, not a prayer.
//    Waivers demand a Grant, and the only way to mint one is authorize,
//    which runs the capability check. The grant carries the scope it was
//    checked against, and decide re-verifies it: a grant is proof of a
//    check, not a substitute for one. (Residual TOCTOU — rights revoked
//    between authorize and decide — is why the write path re-checks inside
//    its transaction; types move the check earlier, they don't remove it.)
// ---------------------------------------------------------------------------
object WaiverAuthority:
  opaque type Grant = (UserId, Scope)

  def authorize(user: UserId, assignments: List[RoleAssignment],
                venue: VenueId): Option[Grant] =
    if can(assignments, user, venue, Capability.WaivePenalty) then
      Some((user, Scope.AtVenue(venue)))
    else None

  extension (g: Grant)
    def user: UserId = g._1
    def scope: Scope = g._2

// ---------------------------------------------------------------------------
// The decision itself: a pure function, no database, no clock, no side effects.
// ---------------------------------------------------------------------------
// Callers pass IDs, not existence proofs: a VenueId builds with no row
// behind it. What it always carries is its org, so scope checks read the
// venue's org off the ID instead of trusting the caller's word. Existence
// stays the outer layer's job; with no grant, venue goes unused.
def decide(policy: Policy, classStart: Instant, now: Instant,
           venue: VenueId,
           waiver: Option[Waiver]): Cancellation =
  val cutoff = classStart.minus(policy.window.duration)
  if !now.isAfter(cutoff) then Cancellation.OnTime(now)
  else waiver match
    // A grant minted for another scope is not a waiver here: fail closed
    // toward the policy outcome: deny by default.
    case Some(w) if appliesAt(w.grant.scope, venue) =>
      Cancellation.LateWaived(now, w)
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
final case class Stamp private (credits: Int)

object Stamp:
  def of(credits: Int): Either[String, Stamp] =
    if credits < 0 then Left("stamp must not be negative")
    else Right(new Stamp(credits))

def refundAmount(c: Cancellation, spent: Stamp): Int = c match
  case Cancellation.LatePenalised(_, Enforcement.LoseCredit) => 0
  case _                                                      => spent.credits

def refund(e: Entitlement, amount: Int): Entitlement = (e, amount) match
  case (Entitlement.Unlimited, _)  => Entitlement.Unlimited
  case (Entitlement.Credits(b), a) => Entitlement.Credits(b.add(a))

// ---------------------------------------------------------------------------
// 9. Records are mandatory, not optional.
//    Cancel paths return exactly one CancellationRecord — no cancelled booking without
//    one. CancellationRecord.of refuses hand-built nonsense: cause must agree with
//    status (NoShow with NoShow, terminal statuses otherwise; Booked and
//    friends never carry records) and the refund cannot exceed the stamp.
//    Retroactive waiver (reassess) compensates only a standing LOSE_CREDIT
//    forfeit; everything else names its refusal, mirroring InvalidWaiver.
// ---------------------------------------------------------------------------
enum Cause:
  case MemberCancel, StaffDecision, SessionCancelled, NoShow

final case class CancellationRecord private (
  booking: BookingId, cause: Cause, status: BookingStatus, refunded: Int,
  spent: Stamp
)

object CancellationRecord:
  def of(booking: BookingId, cause: Cause, status: BookingStatus, refunded: Int,
         spent: Stamp): Either[String, CancellationRecord] =
    val causeOk = (cause, status) match
      case (Cause.NoShow, BookingStatus.NoShow) => true
      case (Cause.NoShow, _)                     => false
      case (_, BookingStatus.NoShow)             => false
      case (_, BookingStatus.Cancelled(_) | BookingStatus.LateCancelled(_)) =>
        true
      case _ => false
    if !causeOk then Left("record cause and status disagree")
    else if refunded < 0 || refunded > spent.credits then
      Left("refund exceeds stamp")
    else Right(new CancellationRecord(booking, cause, status, refunded, spent))

// The only ways to make a CancellationRecord. Member cancels derive status from the
// decision; staff and provider cancels never penalise (full stamp refund,
// status CANCELLED even when late — the cause, not the policy, explains
// why); no-shows keep the stamp spent.
// Cancel paths return the flipped booking with its record: the status flip
// and the record write are one atomic pair, the way the transaction does it.
def cancelMember(policy: Policy, venue: VenueId, start: Instant, now: Instant,
                 booking: Booking, waiver: Option[Waiver]): (Booking, CancellationRecord) =
  val cancellation = decide(policy, start, now, venue, waiver)
  val status = cancellation match
    case o: Cancellation.OnTime         => BookingStatus.Cancelled(o)
    case l: Cancellation.LateAllowed   => BookingStatus.LateCancelled(l)
    case l: Cancellation.LatePenalised => BookingStatus.LateCancelled(l)
    case l: Cancellation.LateWaived    => BookingStatus.LateCancelled(l)
  val record = CancellationRecord
    .of(booking.id, Cause.MemberCancel, status,
        refundAmount(cancellation, booking.spent), booking.spent)
    .toOption.get
  (booking.copy(status = status), record)

def cancelUnpenalised(cause: Cause, policy: Policy, venue: VenueId,
                      start: Instant, now: Instant,
                      booking: Booking): (Booking, CancellationRecord) =
  val cutoff = start.minus(policy.window.duration)
  val status =
    if !now.isAfter(cutoff) then BookingStatus.Cancelled(Cancellation.OnTime(now))
    else BookingStatus.Cancelled(Cancellation.LateAllowed(now))
  val record = CancellationRecord.of(booking.id, cause, status, booking.spent.credits, booking.spent)
    .toOption.get
  (booking.copy(status = status), record)

def cancelStaff(policy: Policy, venue: VenueId, start: Instant, now: Instant,
                booking: Booking): (Booking, CancellationRecord) =
  cancelUnpenalised(Cause.StaffDecision, policy, venue, start, now, booking)

def cancelSession(policy: Policy, venue: VenueId, start: Instant, now: Instant,
                  booking: Booking): (Booking, CancellationRecord) =
  cancelUnpenalised(Cause.SessionCancelled, policy, venue, start, now, booking)

def markNoShow(booking: Booking): (Booking, CancellationRecord) =
  val record = CancellationRecord.of(booking.id, Cause.NoShow, BookingStatus.NoShow, 0, booking.spent)
    .toOption.get
  (booking.copy(status = BookingStatus.NoShow), record)

// Retroactive waiver: compensates a standing LOSE_CREDIT forfeit, nothing
// else. The grant is re-verified against the venue here, the way the write
// transaction re-checks — a stored record is no fresher than a passed ID.
def reassess(record: CancellationRecord, venue: VenueId, waiver: Waiver): Either[String, Int] =
  if !appliesAt(waiver.grant.scope, venue) then Left("waiver grant covers another scope")
  else record match
    case CancellationRecord(_, Cause.MemberCancel,
                BookingStatus.LateCancelled(
                  Cancellation.LatePenalised(_, Enforcement.LoseCredit)),
                0, spent) if spent.credits > 0 =>
      Right(spent.credits)
    case CancellationRecord(_, Cause.MemberCancel,
                BookingStatus.LateCancelled(
                  Cancellation.LatePenalised(_, Enforcement.LoseCredit)),
                _, _) =>
      Left("no standing forfeit to waive")
    case _ =>
      Left("record carries no compensable forfeit")

// ---------------------------------------------------------------------------
@main def demo(): Unit =
  val window = CancelWindow.of(Duration.ofHours(12)).toOption.get
  val home = VenueId(OrgId(1), 2)
  val fee = Enforcement.Fee(Money.of(1500).toOption.get)
  val policy = Policy.of(SessionKind.Private, window, fee).toOption.get
  println(Policy.of(SessionKind.Group, window, fee)) // Left: fee is private-only
  val start  = Instant.parse("2026-11-02T18:00:00Z")

  val late = decide(policy, start, Instant.parse("2026-11-02T10:00:00Z"), home, None)
  println(s"late cancel under fee policy -> $late")
  println(s"fee owed on that cancellation -> ${lateFee(late)}")
  val spent = Stamp.of(2).toOption.get // credit_cost > 1: the stamp flows back
  val back = refundAmount(late, spent)
  println(s"booking spent ${spent.credits} credits, refunded $back" +
    " (a fee does not take the credits)")
  println(s"balance Credits(3) + $back refunded = " +
    refund(Entitlement.Credits(CreditBalance.of(3).toOption.get), back))

  val assignments = List(RoleAssignment(UserId(7), Role.Frontdesk, Scope.AtVenue(home)))

  val grant = WaiverAuthority.authorize(UserId(7), assignments, home)
  println(s"waiver grant for frontdesk -> $grant")
  val waiver = for
    g <- grant
    r <- Reason.of("teacher double-booked the room").toOption
  yield Waiver(g, r)
  val memberGrant = WaiverAuthority.authorize(UserId(9), assignments, home)
  println(s"waiver grant for plain member -> $memberGrant") // None: no waive rights

  val waived = decide(policy, start, Instant.parse("2026-11-02T10:00:00Z"), home, waiver)
  println(s"same cancel, waived by staff -> $waived")
  println(s"fee owed after waiver -> ${lateFee(waived)}")

  println(s"zero window (baseline) accepted -> ${CancelWindow.of(Duration.ZERO)}")
  println(s"negative window rejected -> ${CancelWindow.of(Duration.ofHours(-1))}")

  println(s"frontdesk of venue 2 waives at venue 2 -> " +
    can(assignments, UserId(7), home, Capability.WaivePenalty))
  println(s"frontdesk of venue 2 waives at venue 3 -> " +
    can(assignments, UserId(7), VenueId(OrgId(1), 3), Capability.WaivePenalty))
  println(s"frontdesk enters free at venue 2 -> " +
    isDutyStaff(assignments, UserId(7), home))
  println(s"frontdesk operates door at venue 2 -> " +
    canOperateDoor(assignments, UserId(7), home))
  val wide = List(RoleAssignment(UserId(7), Role.Manager, Scope.OrgWide(OrgId(1))))
  println(s"org-wide manager enters free at home venue -> " +
    isDutyStaff(wide, UserId(7), home))
  println(s"org-wide manager enters free at foreign venue -> " +
    isDutyStaff(wide, UserId(7), VenueId(OrgId(9), 3))) // false: venue owns its org
  val lateAt = Instant.parse("2026-11-02T10:00:00Z")
  val booking = Booking(BookingId(1), UserId(3), SessionId(5), MembershipId(7),
                          BookingStatus.Booked, spent)
  val (flipped, memberRecord) = cancelMember(policy, home, start, lateAt, booking, None)
  println(s"member late cancel flips booking and writes one record -> $flipped / $memberRecord")
  println(s"retroactive waiver of fee record -> ${reassess(memberRecord, home, waiver.get)}")
  val losePolicy = Policy.of(SessionKind.Group, window, Enforcement.LoseCredit).toOption.get
  val forfeitBooking = booking.copy(id = BookingId(2))
  val (_, forfeit) = cancelMember(losePolicy, home, start, lateAt, forfeitBooking, None)
  println(s"member late lose-credit cancel -> $forfeit")
  println(s"retroactive waiver of forfeit -> ${reassess(forfeit, home, waiver.get)}")
  println(s"staff cancel flips booking and writes one record -> ${cancelStaff(policy, home, start, lateAt, booking)}")
