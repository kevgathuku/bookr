package bookr

import java.time.{Duration, Instant, LocalDate}

import Types.*

// Waitlist / promotion / hold lifecycle, asserted.
class WaitlistSuite extends munit.FunSuite:
  val venue = VenueId(OrgId(1), 2)
  val start = Instant.parse("2026-11-02T18:00:00Z")
  val before = Instant.parse("2026-11-02T10:00:00Z")
  val alice = UserId(3)

  def membership(balance: Int): Membership =
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

  def booked(id: Long, spent: Int): Booking =
    Booking(
      id = BookingId(id),
      member = alice,
      session = SessionId(5),
      membership = MembershipId(7),
      status = BookingStatus.Booked,
      spent = Stamp.of(spent).toOption.get
    )

  def held(id: Long, until: Instant): Booking =
    Booking(
      id = BookingId(id),
      member = alice,
      session = SessionId(5),
      membership = MembershipId(7),
      status = BookingStatus.Held(until),
      spent = Stamp.of(0).toOption.get
    )

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

  def waiver: Waiver =
    val assignments =
      List(RoleAssignment(UserId(7), Role.Frontdesk, Scope.AtVenue(venue)))
    val grant = WaiverAuthority.authorize(UserId(7), assignments, venue).get
    Waiver(grant, Reason.of("teacher double-booked the room").toOption.get)

  def losePolicy: Policy =
    Policy
      .of(
        window = CancelWindow.of(Duration.ofHours(12)).toOption.get,
        enforcement = Enforcement.LoseCredit
      )
      .toOption
      .get

  test("joining stamps zero and queues, whatever the booking carried"):
    val queue = joinWaitlist(queue = Nil, booking = waiter(1))
    assertEquals(queue.map(_.status), List(BookingStatus.Waitlisted))
    assertEquals(queue.map(_.spent), List(Stamp.of(0).toOption.get))

  test("promotion seats the head and drops it from the queue"):
    val queue = joinWaitlist(
      joinWaitlist(queue = Nil, booking = waiter(1)),
      booking = waiter(2)
    )
    val (rest, promoted) =
      promoteHead(queue = queue, now = before, openSeats = 1)
    val head = promoted.get
    assertEquals(
      head.status,
      BookingStatus.Held(before.plus(Duration.ofMinutes(60)))
    )
    assertEquals(head.spent, Stamp.of(0).toOption.get)
    // The seated head leaves: only waiters remain, in order.
    assertEquals(rest.map(_.id), List(BookingId(2)))
    assertEquals(rest.map(_.status), List(BookingStatus.Waitlisted))

  test("promotion is a natural no-op when full or the queue is empty"):
    assertEquals(
      promoteHead(queue = Nil, now = before, openSeats = 1),
      (Nil, None)
    )
    val queue = joinWaitlist(queue = Nil, booking = waiter(1))
    assertEquals(
      promoteHead(queue = queue, now = before, openSeats = 0)._2,
      None
    )

  test("confirm spends and claims the seat"):
    val queue = joinWaitlist(queue = Nil, booking = waiter(1))
    val (_, Some(head)) =
      promoteHead(queue = queue, now = before, openSeats = 1)
    val (claimed, debited, _) =
      confirmHold(
        booking = head,
        membership = membership(5),
        session = venueSession,
        now = before,
        log = Ledger.empty
      ).toOption.get
    assertEquals(claimed.status, BookingStatus.Booked)
    assertEquals(claimed.spent, Stamp.of(2).toOption.get)
    assertEquals(debited.entitlement, credits(3))

  test("confirm requires a held booking"):
    assertEquals(
      confirmHold(
        booking = waiter(1),
        membership = membership(5),
        session = venueSession,
        now = before,
        log = Ledger.empty
      ),
      Left("no hold to confirm")
    )

  test("confirm fails cleanly on insufficient credits"):
    val queue = joinWaitlist(queue = Nil, booking = waiter(1))
    val (_, Some(head)) =
      promoteHead(queue = queue, now = before, openSeats = 1)
    assertEquals(
      confirmHold(
        booking = head,
        membership = membership(1),
        session = venueSession,
        now = before,
        log = Ledger.empty
      ),
      Left("insufficient credits")
    )

  test("confirm requires a valid membership"):
    val old = Membership
      .of(
        id = MembershipId(7),
        user = alice,
        plan = PlanKind.CreditPack,
        startsOn = LocalDate.of(2025, 1, 1),
        endsOn = LocalDate.of(2025, 12, 31),
        entitlement = credits(5)
      )
      .toOption
      .get
    val queue = joinWaitlist(queue = Nil, booking = waiter(1))
    val (_, Some(head)) =
      promoteHead(queue = queue, now = before, openSeats = 1)
    assertEquals(
      confirmHold(
        booking = head,
        membership = old,
        session = venueSession,
        now = before,
        log = Ledger.empty
      ),
      Left("membership is not currently valid")
    )

  test("confirm requires an open session"):
    val closed =
      closeSession(venueSession, Reason.of("room flooded").toOption.get, before)
    val queue = joinWaitlist(queue = Nil, booking = waiter(1))
    val (_, Some(head)) =
      promoteHead(queue = queue, now = before, openSeats = 1)
    assertEquals(
      confirmHold(
        booking = head,
        membership = membership(5),
        session = closed,
        now = before,
        log = Ledger.empty
      ),
      Left("session is cancelled")
    )

  test("confirm refuses an already-spent hold"):
    val spent =
      held(1, before.plusSeconds(3600)).copy(spent = Stamp.of(2).toOption.get)
    assertEquals(
      confirmHold(
        booking = spent,
        membership = membership(5),
        session = venueSession,
        now = before,
        log = Ledger.empty
      ),
      Left("hold is already spent")
    )

  test("decline releases immediately with no money moved"):
    val queue = joinWaitlist(queue = Nil, booking = waiter(1))
    val (_, Some(head)) =
      promoteHead(queue = queue, now = before, openSeats = 1)
    val (released, record) =
      declineHold(booking = head, now = before).toOption.get
    assertEquals(
      released.status,
      BookingStatus.Cancelled(Cancellation.OnTime(before))
    )
    assertEquals(record.cause, Cause.Unclaimed)
    assertEquals(record.refunded, 0)

  test("decline without a hold is refused"):
    assertEquals(
      declineHold(booking = waiter(1), now = before),
      Left("no hold to decline")
    )

  test(
    "cancel on a held booking releases as unclaimed, even when late and waived"
  ):
    val queue = joinWaitlist(queue = Nil, booking = waiter(1))
    val (_, Some(head)) =
      promoteHead(queue = queue, now = before, openSeats = 1)
    val (released, record) =
      cancelMember(
        policy = losePolicy,
        venue = venue,
        start = start,
        now = before,
        booking = head,
        waiver = Some(waiver)
      )
    assertEquals(record.cause, Cause.Unclaimed)
    assertEquals(record.refunded, 0)
    assertEquals(
      released.status,
      BookingStatus.Cancelled(Cancellation.OnTime(before))
    )

  test("sweep releases expired holds and drops them from the queue"):
    val queue = List(held(1, before.minusSeconds(1)), waiter(2))
    val (kept, released) = sweepHolds(bookings = queue, now = before)
    assertEquals(kept.map(_.id), List(BookingId(2)))
    assertEquals(released.map(_._1.id), List(BookingId(1)))
    assertEquals(released.map(_._2.cause), List(Cause.Unclaimed))
    assertEquals(released.map(_._2.refunded), List(0))

  test("a hold expiring exactly now is released"):
    val queue = List(held(1, before))
    val (kept, released) = sweepHolds(bookings = queue, now = before)
    assertEquals(kept, Nil)
    assertEquals(released.map(_._2.cause), List(Cause.Unclaimed))

  test("sweep keeps unexpired holds in place"):
    val queue = List(held(1, before.plusSeconds(3600)))
    val (kept, released) = sweepHolds(bookings = queue, now = before)
    assertEquals(kept, queue)
    assertEquals(released, Nil)

  test("sweep ignores bookings without holds"):
    val queue =
      List(booked(1, 2), booked(2, 0).copy(status = BookingStatus.Attended))
    val (kept, released) = sweepHolds(bookings = queue, now = before)
    assertEquals(kept, queue)
    assertEquals(released, Nil)

  test("cancel frees the seat and the head is promoted into it"):
    val queue = joinWaitlist(queue = Nil, booking = waiter(9))
    val seated = booked(1, 2)
    val (_, _) = cancelSession(
      policy = losePolicy,
      venue = venue,
      start = start,
      now = before,
      booking = seated
    )
    val (filled, promoted) =
      promoteHead(queue = queue, now = before, openSeats = 1)
    assertEquals(filled, Nil)
    assertEquals(
      promoted.get.status,
      BookingStatus.Held(before.plus(Duration.ofMinutes(60)))
    )
    assertEquals(promoted.get.spent, Stamp.of(0).toOption.get)
    assertEquals(promoted.map(_.id), Some(BookingId(9)))

  test("an expired holder can rejoin at the back while the session is open"):
    val session = Session(
      id = SessionId(5),
      venue = venue,
      teacher = UserId(9),
      startsAt = start,
      durationMinutes = 60,
      capacity = 15,
      cancelledAt = None,
      creditCost = 2
    )
    assertEquals(requireOpen(session, before), Right(session))
    val queue = joinWaitlist(
      joinWaitlist(queue = Nil, booking = waiter(1)),
      booking = waiter(2)
    )
    val (rest, first) = promoteHead(queue = queue, now = before, openSeats = 1)
    assertEquals(rest.map(_.id), List(BookingId(2)))
    val sweptAt = before.plus(HoldWindow).plusSeconds(1)
    val (kept, released) =
      sweepHolds(bookings = first.toList ++ rest, now = sweptAt)
    // The old row stays terminal: history is not rewritten.
    assertEquals(released.map(_._1.id), List(BookingId(1)))
    assertEquals(
      released.head._2.status,
      BookingStatus.Cancelled(Cancellation.OnTime(sweptAt))
    )
    // Rejoining takes a fresh booking id and lands at the back with no spend.
    val rejoin = Booking(
      id = BookingId(3),
      member = alice,
      session = SessionId(5),
      membership = MembershipId(7),
      status = BookingStatus.Booked,
      spent = Stamp.of(0).toOption.get
    )
    val rejoined = joinWaitlist(queue = kept, booking = rejoin)
    assertEquals(rejoined.map(_.id), List(BookingId(2), BookingId(3)))
    assertEquals(rejoined.last.status, BookingStatus.Waitlisted)
    assertEquals(rejoined.last.spent, Stamp.of(0).toOption.get)

  def credits(n: Int): Entitlement =
    Entitlement.Credits(CreditBalance.of(n).toOption.get)
