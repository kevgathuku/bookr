package bookr

import java.time.{Duration, Instant, LocalDate}

import Types.*

// The ledger is append-only: every spend and refund writes a row.
class LedgerSuite extends munit.FunSuite:
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

  def session(cost: Int): Session =
    Session(
      id = SessionId(5),
      venue = venue,
      teacher = UserId(9),
      startsAt = start,
      durationMinutes = 60,
      capacity = 15,
      cancelledAt = None,
      creditCost = cost
    )

  def waiver: Waiver =
    val assignments =
      List(RoleAssignment(UserId(7), Role.Frontdesk, Scope.AtVenue(venue)))
    val grant = WaiverAuthority.authorize(UserId(7), assignments, venue).get
    Waiver(grant, Reason.of("teacher double-booked the room").toOption.get)

  test("booking appends a spend entry"):
    val (_, _, log, _) =
      book(
        id = BookingId(1),
        session = session(2),
        membership = membership(5),
        member = alice,
        existing = Nil,
        now = before,
        log = Ledger.empty,
        trail = Trail.empty
      ).toOption.get
    assertEquals(
      log.entries,
      List(
        LedgerEntry(
          BookingId(1),
          MembershipId(7),
          -2,
          2,
          LedgerReason.Spend,
          before
        )
      )
    )

  test("monthly booking appends a value-only row"):
    val monthly =
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
    val (_, _, log, _) =
      book(
        id = BookingId(1),
        session = session(2),
        membership = monthly,
        member = alice,
        existing = Nil,
        now = before,
        log = Ledger.empty,
        trail = Trail.empty
      ).toOption.get
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
    // Unlimited consumption is invisible to money but visible to value.
    assertEquals(log.balanceOf(MembershipId(7)), 0)
    assertEquals(log.valueOf(MembershipId(7)), 2)

  test(
    "a free session writes a row, so free bookings stay visible"
  ):
    val (_, _, log, _) =
      book(
        id = BookingId(1),
        session = session(0),
        membership = membership(5),
        member = alice,
        existing = Nil,
        now = before,
        log = Ledger.empty,
        trail = Trail.empty
      ).toOption.get
    // Neither money nor value moved, but the row marks the booking - that
    // is how free sessions can be counted for attendance.
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

  test("zero refunds post nothing"):
    val noRefund = CancellationRecord.of(
      BookingId(1),
      Cause.SessionCancelled,
      BookingStatus.Cancelled(Cancellation.OnTime(before)),
      0,
      Stamp.of(0).toOption.get
    )
    assertEquals(noRefund.map(_.refunded), Right(0))
    val (log, _) =
      settle(Ledger.empty, noRefund.toOption.get, membership(0), before)
    assertEquals(log.entries, Nil)

  test("a waived forfeit is compensated, not refunded"):
    val (booked, debited, log1, _) =
      book(
        id = BookingId(1),
        session = session(2),
        membership = membership(5),
        member = alice,
        existing = Nil,
        now = before,
        log = Ledger.empty,
        trail = Trail.empty
      ).toOption.get
    val losePolicy =
      Policy
        .of(
          window = CancelWindow.of(Duration.ofHours(12)).toOption.get,
          enforcement = Enforcement.LoseCredit
        )
        .toOption
        .get
    val (_, record, _) =
      cancelMember(
        policy = losePolicy,
        venue = venue,
        start = start,
        now = before,
        booking = booked,
        waiver = None,
        trail = Trail.empty
      )
    assertEquals(record.refunded, 0)
    val (compensated, log2) = reassess(
      record = record,
      membership = debited,
      venue = venue,
      waiver = waiver,
      now = before,
      log = log1
    ).toOption.get
    assertEquals(compensated, 2)
    assertEquals(
      log2.entries,
      List(
        LedgerEntry(
          BookingId(1),
          MembershipId(7),
          2,
          0,
          LedgerReason.Compensation,
          before
        ),
        LedgerEntry(
          BookingId(1),
          MembershipId(7),
          -2,
          2,
          LedgerReason.Spend,
          before
        )
      )
    )
    assertEquals(log2.balanceOf(MembershipId(7)), 0)
