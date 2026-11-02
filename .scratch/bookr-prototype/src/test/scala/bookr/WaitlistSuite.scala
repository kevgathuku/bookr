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

  // Promotes the head of a queue and hands back the seat and the trail.
  // The seat is not an Option: these tests all expect a promotion.
  def seatHead(queue: List[Booking], trail: Trail): (Booking, Trail) =
    val (_, head, next) =
      promoteHead(queue = queue, now = before, openSeats = 1, trail = trail)
    (head.get, next)

  test("joining stamps zero and queues, whatever the booking carried"):
    val (queue, _) = joinWaitlist(
      queue = Nil,
      booking = waiter(1),
      now = before,
      trail = Trail.empty
    )
    assertEquals(queue.map(_.status), List(BookingStatus.Waitlisted))
    assertEquals(queue.map(_.spent), List(Stamp.of(0).toOption.get))

  test("promotion seats the head and drops it from the queue"):
    val (one, _) = joinWaitlist(
      queue = Nil,
      booking = waiter(1),
      now = before,
      trail = Trail.empty
    )
    val (queue, _) = joinWaitlist(
      queue = one,
      booking = waiter(2),
      now = before,
      trail = Trail.empty
    )
    val (rest, promoted, _) =
      promoteHead(
        queue = queue,
        now = before,
        openSeats = 1,
        trail = Trail.empty
      )
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
      promoteHead(
        queue = Nil,
        now = before,
        openSeats = 1,
        trail = Trail.empty
      ),
      (Nil, None, Trail.empty)
    )
    val (queue, _) = joinWaitlist(
      queue = Nil,
      booking = waiter(1),
      now = before,
      trail = Trail.empty
    )
    assertEquals(
      promoteHead(
        queue = queue,
        now = before,
        openSeats = 0,
        trail = Trail.empty
      )._2,
      None
    )

  test("confirm spends and claims the seat"):
    val (queue, _) = joinWaitlist(
      queue = Nil,
      booking = waiter(1),
      now = before,
      trail = Trail.empty
    )
    val (head, _) = seatHead(queue = queue, trail = Trail.empty)
    val (claimed, debited, _, _) =
      confirmHold(
        booking = head,
        membership = membership(5),
        session = venueSession,
        now = before,
        log = Ledger.empty,
        trail = Trail.empty
      ).toOption.get
    assertEquals(claimed.status, BookingStatus.Booked)
    assertEquals(claimed.spent, Stamp.of(2).toOption.get)
    assertEquals(debited.entitlement, credits(3))

  test("a free session confirm writes a ledger row"):
    val (queue, _) = joinWaitlist(
      queue = Nil,
      booking = waiter(1),
      now = before,
      trail = Trail.empty
    )
    val (head, trail) = seatHead(queue = queue, trail = Trail.empty)
    val (_, _, log, _) =
      confirmHold(
        booking = head,
        membership = membership(5),
        session = venueSession.copy(creditCost = 0),
        now = before,
        log = Ledger.empty,
        trail = trail
      ).toOption.get
    // Neither money nor value moved, but the row marks the claim.
    assertEquals(
      log.entries,
      List(
        LedgerEntry(
          BookingId(1),
          MembershipId(7),
          0,
          0,
          LedgerReason.Spend,
          before
        )
      )
    )

  test("unlimited confirm writes a value-only row"):
    val (queue, _) = joinWaitlist(
      queue = Nil,
      booking = waiter(1),
      now = before,
      trail = Trail.empty
    )
    val (head, _) = seatHead(queue = queue, trail = Trail.empty)
    val (claimed, debited, log, _) =
      confirmHold(
        booking = head,
        membership = monthly,
        session = venueSession,
        now = before,
        log = Ledger.empty,
        trail = Trail.empty
      ).toOption.get
    assertEquals(claimed.status, BookingStatus.Booked)
    assertEquals(claimed.spent, Stamp.of(0).toOption.get)
    assertEquals(debited.entitlement, Entitlement.Unlimited)
    assertEquals(
      log.entries,
      List(
        LedgerEntry(
          BookingId(1),
          MembershipId(7),
          0,
          2,
          LedgerReason.Spend,
          before
        )
      )
    )
    assertEquals(log.balanceOf(MembershipId(7)), 0)
    assertEquals(log.valueOf(MembershipId(7)), 2)

  test("confirm requires a held booking"):
    assertEquals(
      confirmHold(
        booking = waiter(1),
        membership = membership(5),
        session = venueSession,
        now = before,
        log = Ledger.empty,
        trail = Trail.empty
      ),
      Left("no hold to confirm")
    )

  test("confirm fails cleanly on insufficient credits"):
    val (queue, _) = joinWaitlist(
      queue = Nil,
      booking = waiter(1),
      now = before,
      trail = Trail.empty
    )
    val (head, _) = seatHead(queue = queue, trail = Trail.empty)
    assertEquals(
      confirmHold(
        booking = head,
        membership = membership(1),
        session = venueSession,
        now = before,
        log = Ledger.empty,
        trail = Trail.empty
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
    val (queue, _) = joinWaitlist(
      queue = Nil,
      booking = waiter(1),
      now = before,
      trail = Trail.empty
    )
    val (head, _) = seatHead(queue = queue, trail = Trail.empty)
    assertEquals(
      confirmHold(
        booking = head,
        membership = old,
        session = venueSession,
        now = before,
        log = Ledger.empty,
        trail = Trail.empty
      ),
      Left("membership is not currently valid")
    )

  test("confirm requires an open session"):
    val closed =
      closeSession(venueSession, Reason.of("room flooded").toOption.get, before)
    val (queue, _) = joinWaitlist(
      queue = Nil,
      booking = waiter(1),
      now = before,
      trail = Trail.empty
    )
    val (head, _) = seatHead(queue = queue, trail = Trail.empty)
    assertEquals(
      confirmHold(
        booking = head,
        membership = membership(5),
        session = closed,
        now = before,
        log = Ledger.empty,
        trail = Trail.empty
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
        log = Ledger.empty,
        trail = Trail.empty
      ),
      Left("hold is already spent")
    )

  test("decline releases immediately with no money moved"):
    val (queue, _) = joinWaitlist(
      queue = Nil,
      booking = waiter(1),
      now = before,
      trail = Trail.empty
    )
    val (head, _) = seatHead(queue = queue, trail = Trail.empty)
    val (released, record, _) =
      declineHold(
        booking = head,
        now = before,
        trail = Trail.empty
      ).toOption.get
    assertEquals(
      released.status,
      BookingStatus.Cancelled(Cancellation.OnTime(before))
    )
    assertEquals(record.cause, Cause.Unclaimed)
    assertEquals(record.refunded, 0)

  test("decline without a hold is refused"):
    assertEquals(
      declineHold(booking = waiter(1), now = before, trail = Trail.empty),
      Left("no hold to decline")
    )

  test(
    "cancel on a held booking releases as unclaimed, even when late and waived"
  ):
    val (queue, _) = joinWaitlist(
      queue = Nil,
      booking = waiter(1),
      now = before,
      trail = Trail.empty
    )
    val (head, _) = seatHead(queue = queue, trail = Trail.empty)
    val (released, record, _) =
      cancelMember(
        policy = losePolicy,
        venue = venue,
        start = start,
        now = before,
        booking = head,
        waiver = Some(waiver),
        trail = Trail.empty
      )
    assertEquals(record.cause, Cause.Unclaimed)
    assertEquals(record.refunded, 0)
    assertEquals(
      released.status,
      BookingStatus.Cancelled(Cancellation.OnTime(before))
    )

  test("sweep releases expired holds and drops them from the queue"):
    val queue = List(held(1, before.minusSeconds(1)), waiter(2))
    val (kept, released, _) =
      sweepHolds(bookings = queue, now = before, trail = Trail.empty)
    assertEquals(kept.map(_.id), List(BookingId(2)))
    assertEquals(released.map(_._1.id), List(BookingId(1)))
    assertEquals(released.map(_._2.cause), List(Cause.Unclaimed))
    assertEquals(released.map(_._2.refunded), List(0))

  test("sweep releases several expired holds, recording every transition"):
    val queue =
      List(held(1, before.minusSeconds(1)), held(2, before.minusSeconds(1)))
    val (kept, released, trail) =
      sweepHolds(bookings = queue, now = before, trail = Trail.empty)
    assertEquals(kept, Nil)
    assertEquals(released.map(_._1.id), List(BookingId(1), BookingId(2)))
    // Both holds must leave a transition: the sweep threads the trail
    // through each release, so one cannot overwrite the other.
    assertEquals(
      trail.forBooking(BookingId(1)).map(_.to),
      List(BookingStatus.Cancelled(Cancellation.OnTime(before)))
    )
    assertEquals(
      trail.forBooking(BookingId(2)).map(_.to),
      List(BookingStatus.Cancelled(Cancellation.OnTime(before)))
    )

  test("a hold expiring exactly now is released"):
    val queue = List(held(1, before))
    val (kept, released, _) =
      sweepHolds(bookings = queue, now = before, trail = Trail.empty)
    assertEquals(kept, Nil)
    assertEquals(released.map(_._2.cause), List(Cause.Unclaimed))

  test("sweep keeps unexpired holds in place"):
    val queue = List(held(1, before.plusSeconds(3600)))
    val (kept, released, _) =
      sweepHolds(bookings = queue, now = before, trail = Trail.empty)
    assertEquals(kept, queue)
    assertEquals(released, Nil)

  test("sweep ignores bookings without holds"):
    val queue =
      List(booked(1, 2), booked(2, 0).copy(status = BookingStatus.Attended))
    val (kept, released, _) =
      sweepHolds(bookings = queue, now = before, trail = Trail.empty)
    assertEquals(kept, queue)
    assertEquals(released, Nil)

  test("cancel frees the seat and the head is promoted into it"):
    val (queue, _) = joinWaitlist(
      queue = Nil,
      booking = waiter(9),
      now = before,
      trail = Trail.empty
    )
    val seated = booked(1, 2)
    val (_, _, _) = cancelSession(
      policy = losePolicy,
      venue = venue,
      start = start,
      now = before,
      booking = seated,
      trail = Trail.empty
    )
    val (filled, promoted, _) =
      promoteHead(
        queue = queue,
        now = before,
        openSeats = 1,
        trail = Trail.empty
      )
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
    val (one, _) = joinWaitlist(
      queue = Nil,
      booking = waiter(1),
      now = before,
      trail = Trail.empty
    )
    val (queue, _) = joinWaitlist(
      queue = one,
      booking = waiter(2),
      now = before,
      trail = Trail.empty
    )
    val (rest, first, _) = promoteHead(
      queue = queue,
      now = before,
      openSeats = 1,
      trail = Trail.empty
    )
    assertEquals(rest.map(_.id), List(BookingId(2)))
    val sweptAt = before.plus(HoldWindow).plusSeconds(1)
    val (kept, released, _) =
      sweepHolds(
        bookings = first.toList ++ rest,
        now = sweptAt,
        trail = Trail.empty
      )
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
    val (rejoined, _) = joinWaitlist(
      queue = kept,
      booking = rejoin,
      now = sweptAt,
      trail = Trail.empty
    )
    assertEquals(rejoined.map(_.id), List(BookingId(2), BookingId(3)))
    assertEquals(rejoined.last.status, BookingStatus.Waitlisted)
    assertEquals(rejoined.last.spent, Stamp.of(0).toOption.get)

  def credits(n: Int): Entitlement =
    Entitlement.Credits(CreditBalance.of(n).toOption.get)
