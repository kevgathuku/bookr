package bookr

import java.time.{Duration, Instant, LocalDate}

import Types.*

// The audit trail: every status change writes exactly one row, whether or
// not money moved.
class TrailSuite extends munit.FunSuite:
  val venue = VenueId(OrgId(1), 2)
  val start = Instant.parse("2026-11-02T18:00:00Z")
  val before = Instant.parse("2026-11-02T10:00:00Z")
  val alice = UserId(3)

  def monthly: Membership =
    Membership
      .of(
        id = MembershipId(7),
        user = alice,
        plan = PlanKind.Monthly,
        startsOn = LocalDate.of(2026, 1, 1),
        endsOn = LocalDate.of(2026, 12, 31),
        entitlement = Entitlement.Unlimited
      )
      .toOption
      .get

  def pack(balance: Int): Membership =
    Membership
      .of(
        id = MembershipId(7),
        user = alice,
        plan = PlanKind.CreditPack,
        startsOn = LocalDate.of(2026, 1, 1),
        endsOn = LocalDate.of(2026, 12, 31),
        entitlement =
          Entitlement.Credits(CreditBalance.of(balance).toOption.get)
      )
      .toOption
      .get

  def waiter(id: Long): Booking =
    Booking(
      id = BookingId(id),
      member = alice,
      session = SessionId(5),
      membership = MembershipId(7),
      status = BookingStatus.Booked,
      spent = Stamp.of(2).toOption.get
    )

  def venueSession: Session =
    Session(
      id = SessionId(5),
      venue = venue,
      teacher = UserId(9),
      startsAt = start,
      durationMinutes = 60,
      capacity = 15,
      cancelledAt = None,
      creditCost = 2
    )

  // Promotes the head of a queue and hands back the seat and the trail.
  // The seat is not an Option: these tests all expect a promotion.
  def seatHead(queue: List[Booking], trail: Trail): (Booking, Trail) =
    val (_, head, next) =
      promoteHead(queue = queue, now = before, openSeats = 1, trail = trail)
    (head.get, next)

  test("booking writes a creation transition"):
    val (_, _, _, trail) =
      book(
        id = BookingId(1),
        session = venueSession,
        membership = pack(5),
        member = alice,
        existing = Nil,
        now = before,
        log = Ledger.empty,
        trail = Trail.empty
      ).toOption.get
    assertEquals(
      trail.forBooking(BookingId(1)),
      List(Transition(BookingId(1), None, BookingStatus.Booked, before))
    )

  test("joining the waitlist writes a transition and touches no money"):
    val (_, trail) =
      joinWaitlist(
        queue = Nil,
        booking = waiter(1),
        now = before,
        trail = Trail.empty
      )
    assertEquals(
      trail.forBooking(BookingId(1)),
      List(
        Transition(BookingId(1), None, BookingStatus.Waitlisted, before)
      )
    )

  test("promotion writes the waitlisted-to-held transition"):
    val (queue, joined) =
      joinWaitlist(
        queue = Nil,
        booking = waiter(1),
        now = before,
        trail = Trail.empty
      )
    val (_, _, trail) =
      promoteHead(queue = queue, now = before, openSeats = 1, trail = joined)
    assertEquals(
      trail.forBooking(BookingId(1)).last,
      Transition(
        BookingId(1),
        Some(BookingStatus.Waitlisted),
        BookingStatus.Held(before.plus(HoldWindow)),
        before
      )
    )

  test("an unlimited confirm writes the held-to-booked transition"):
    val (queue, joined) =
      joinWaitlist(
        queue = Nil,
        booking = waiter(1),
        now = before,
        trail = Trail.empty
      )
    val (held, trail) = seatHead(queue = queue, trail = joined)
    val (_, _, log, confirmed) =
      confirmHold(
        booking = held,
        membership = monthly,
        session = venueSession,
        now = before,
        log = Ledger.empty,
        trail = trail
      ).toOption.get
    // No money moved, and the transition was written anyway: the trail
    // records status, the ledger records money.
    assertEquals(log.balanceOf(MembershipId(7)), 0)
    assertEquals(
      confirmed.forBooking(BookingId(1)).last,
      Transition(
        BookingId(1),
        Some(BookingStatus.Held(before.plus(HoldWindow))),
        BookingStatus.Booked,
        before
      )
    )

  test("a declined hold writes the held-to-cancelled transition"):
    val (queue, joined) =
      joinWaitlist(
        queue = Nil,
        booking = waiter(1),
        now = before,
        trail = Trail.empty
      )
    val (held, trail) = seatHead(queue = queue, trail = joined)
    val (_, _, declined) =
      declineHold(booking = held, now = before, trail = trail).toOption.get
    assertEquals(
      declined.forBooking(BookingId(1)).last,
      Transition(
        BookingId(1),
        Some(BookingStatus.Held(before.plus(HoldWindow))),
        BookingStatus.Cancelled(Cancellation.OnTime(before)),
        before
      )
    )

  test("a promotion that seats nobody writes no transition"):
    val (queue, joined) =
      joinWaitlist(
        queue = Nil,
        booking = waiter(1),
        now = before,
        trail = Trail.empty
      )
    val (_, _, trail) =
      promoteHead(queue = queue, now = before, openSeats = 0, trail = joined)
    assertEquals(
      trail.forBooking(BookingId(1)).map(_.to),
      List(BookingStatus.Waitlisted)
    )

  test("a staff cancel writes the booked-to-cancelled transition"):
    val (_, _, trail) =
      cancelStaff(
        policy = Policy
          .of(
            window = CancelWindow.of(Duration.ofHours(12)).toOption.get,
            enforcement = Enforcement.NoPenalty
          )
          .toOption
          .get,
        venue = venue,
        start = start,
        now = before,
        booking = waiter(1),
        trail = Trail.empty
      )
    assertEquals(
      trail.forBooking(BookingId(1)),
      List(
        Transition(
          BookingId(1),
          Some(BookingStatus.Booked),
          BookingStatus.Cancelled(Cancellation.LateAllowed(before)),
          before
        )
      )
    )

  test("a no-show writes the booked-to-no-show transition"):
    val (_, _, trail) =
      markNoShow(booking = waiter(1), now = before, trail = Trail.empty)
    assertEquals(
      trail.forBooking(BookingId(1)),
      List(
        Transition(
          BookingId(1),
          Some(BookingStatus.Booked),
          BookingStatus.NoShow,
          before
        )
      )
    )

  test("a rejoin under the same id links to the state it left"):
    val (booked, _, _, trail1) =
      book(
        id = BookingId(1),
        session = venueSession,
        membership = pack(5),
        member = alice,
        existing = Nil,
        now = before,
        log = Ledger.empty,
        trail = Trail.empty
      ).toOption.get
    val (cancelled, _, trail2) =
      cancelMember(
        policy = Policy
          .of(
            window = CancelWindow.of(Duration.ofHours(12)).toOption.get,
            enforcement = Enforcement.NoPenalty
          )
          .toOption
          .get,
        venue = venue,
        start = start,
        now = before,
        booking = booked,
        waiver = None,
        trail = trail1
      )
    val (_, trail3) =
      joinWaitlist(
        queue = Nil,
        booking = cancelled,
        now = before,
        trail = trail2
      )
    // The rejoin links to the cancelled state, not to a fresh start.
    assertEquals(
      trail3.forBooking(BookingId(1)).map(_.from),
      List(
        None,
        Some(BookingStatus.Booked),
        Some(BookingStatus.LateCancelled(Cancellation.LateAllowed(before)))
      )
    )
    assertEquals(
      trail3.forBooking(BookingId(1)).last.to,
      BookingStatus.Waitlisted
    )

  test("the trail replays one booking's whole path in time order"):
    val (queue, joined) =
      joinWaitlist(
        queue = Nil,
        booking = waiter(1),
        now = before,
        trail = Trail.empty
      )
    val (held, promoted) = seatHead(queue = queue, trail = joined)
    val later = before.plusSeconds(60)
    val (confirmed, _, _, trail) =
      confirmHold(
        booking = held,
        membership = pack(5),
        session = venueSession,
        now = later,
        log = Ledger.empty,
        trail = promoted
      ).toOption.get
    val (_, _, cancelled) =
      cancelMember(
        policy = Policy
          .of(
            window = CancelWindow.of(Duration.ofHours(12)).toOption.get,
            enforcement = Enforcement.NoPenalty
          )
          .toOption
          .get,
        venue = venue,
        start = start,
        now = later,
        booking = confirmed,
        waiver = None,
        trail = trail
      )
    assertEquals(
      cancelled.forBooking(BookingId(1)).map(_.to),
      List(
        BookingStatus.Waitlisted,
        BookingStatus.Held(before.plus(HoldWindow)),
        BookingStatus.Booked,
        BookingStatus.LateCancelled(Cancellation.LateAllowed(later))
      )
    )
