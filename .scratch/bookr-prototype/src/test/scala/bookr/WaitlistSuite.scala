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

  def booked(id: Long, spent: Int, hold: Option[Instant]): Booking =
    Booking(
      id = BookingId(id),
      member = alice,
      session = SessionId(5),
      membership = MembershipId(7),
      status = BookingStatus.Booked,
      spent = Stamp.of(spent).toOption.get,
      holdUntil = hold
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

  test("joining stamps zero and queues, whatever the booking carried"):
    val queue = joinWaitlist(Nil, waiter(1))
    assertEquals(queue.map(_.status), List(BookingStatus.Waitlisted))
    assertEquals(queue.map(_.spent), List(Stamp.of(0).toOption.get))
    assertEquals(queue.flatMap(_.holdUntil), Nil)

  test("promotion spends at promotion time"):
    val queue = joinWaitlist(Nil, waiter(1))
    val (seated, promoted) =
      promoteHead(
        queue = queue,
        membership = membership(5),
        price = 2,
        now = before,
        openSeats = 1
      )
    val (head, debited) = promoted.get
    assertEquals(head.status, BookingStatus.Booked)
    assertEquals(head.spent, Stamp.of(2).toOption.get)
    assertEquals(head.holdUntil, Some(before.plus(Duration.ofMinutes(60))))
    assertEquals(debited.entitlement, credits(3))
    assertEquals(seated, List(head))

  test("a head that cannot pay stays queued and the seat stays open"):
    val queue = joinWaitlist(Nil, waiter(1))
    val (same, promoted) =
      promoteHead(
        queue = queue,
        membership = membership(1),
        price = 2,
        now = before,
        openSeats = 1
      )
    assertEquals(promoted, None)
    assertEquals(same, queue)

  test("promotion is a natural no-op when full or the queue is empty"):
    assertEquals(
      promoteHead(
        queue = Nil,
        membership = membership(5),
        price = 2,
        now = before,
        openSeats = 1
      )._2,
      None
    )
    val queue = joinWaitlist(Nil, waiter(1))
    assertEquals(
      promoteHead(
        queue = queue,
        membership = membership(5),
        price = 2,
        now = before,
        openSeats = 0
      )._2,
      None
    )

  test("sweep releases expired holds and reports the stamps to credit back"):
    val queue = List(booked(1, 2, Some(before.minusSeconds(1))))
    val (released, refunds) = sweepHolds(queue, before)
    assertEquals(
      released.map(_.status),
      List(BookingStatus.Cancelled(Cancellation.OnTime(before)))
    )
    assertEquals(released.flatMap(_.holdUntil), Nil)
    assertEquals(refunds, List((BookingId(1), 2)))
    // Round trip: the stamp flows back to the balance it came from.
    assertEquals(refund(credits(3), 2), credits(5))

  test("sweep keeps unexpired holds"):
    val queue = List(booked(1, 2, Some(before.plusSeconds(3600))))
    val (same, refunds) = sweepHolds(queue, before)
    assertEquals(same, queue)
    assertEquals(refunds, Nil)

  test("sweep ignores stale holds on non-BOOKED rows"):
    val attended = booked(1, 2, Some(before.minusSeconds(1))).copy(
      status = BookingStatus.Attended
    )
    val (same, refunds) = sweepHolds(List(attended), before)
    assertEquals(same, List(attended))
    assertEquals(refunds, Nil)

  test("cancel frees the seat and the head is promoted into it"):
    val policy =
      Policy
        .of(
          window = CancelWindow.of(Duration.ofHours(12)).toOption.get,
          enforcement = Enforcement.LoseCredit
        )
        .toOption
        .get
    val queue = joinWaitlist(Nil, waiter(9))
    val seated = booked(1, 2, None)
    val (_, _) = cancelSession(policy, venue, start, before, seated)
    val (filled, promoted) =
      promoteHead(
        queue = queue,
        membership = membership(5),
        price = 2,
        now = before,
        openSeats = 1
      )
    assertEquals(promoted.get._1.status, BookingStatus.Booked)
    assertEquals(promoted.get._1.spent, Stamp.of(2).toOption.get)
    assertEquals(filled.map(_.id), List(BookingId(9)))

  def credits(n: Int): Entitlement =
    Entitlement.Credits(CreditBalance.of(n).toOption.get)
