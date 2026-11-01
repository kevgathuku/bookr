package bookr

import java.time.{Duration, Instant, LocalDate}

import Types.*

// Booking creation: spend math, guards, and the natural key, asserted.
class BookingSuite extends munit.FunSuite:
  val venue = VenueId(OrgId(1), 2)
  val start = Instant.parse("2026-11-02T18:00:00Z")
  val before = Instant.parse("2026-11-02T10:00:00Z")
  val alice = UserId(3)
  val jan = (LocalDate.of(2026, 1, 1), LocalDate.of(2026, 12, 31))

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

  def pack(balance: Int, user: UserId = alice): Membership =
    Membership
      .of(
        id = MembershipId(7),
        user = user,
        plan = PlanKind.CreditPack,
        startsOn = jan._1,
        endsOn = jan._2,
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
        startsOn = jan._1,
        endsOn = jan._2,
        entitlement = Entitlement.Unlimited
      )
      .toOption
      .get

  def policy: Policy =
    Policy
      .of(
        window = CancelWindow.of(Duration.ofHours(12)).toOption.get,
        enforcement = Enforcement.LoseCredit
      )
      .toOption
      .get

  test("booking spends the session's credit cost, not a hardcoded amount"):
    val (booked, debited, log) =
      book(
        id = BookingId(1),
        session = session(2),
        membership = pack(5),
        member = alice,
        existing = Nil,
        now = before,
        log = Ledger.empty
      ).toOption.get
    assertEquals(booked.status, BookingStatus.Booked)
    assertEquals(booked.spent, Stamp.of(2).toOption.get)
    assertEquals(booked.session, SessionId(5))
    assertEquals(booked.membership, MembershipId(7))
    assertEquals(debited.entitlement, credits(3))
    assertEquals(
      log.entries,
      List(
        LedgerEntry(
          BookingId(1),
          MembershipId(7),
          -2,
          LedgerReason.Spend,
          before
        )
      )
    )

  test("a different session cost debits differently"):
    val (_, debited, _) =
      book(
        id = BookingId(1),
        session = session(3),
        membership = pack(5),
        member = alice,
        existing = Nil,
        now = before,
        log = Ledger.empty
      ).toOption.get
    assertEquals(debited.entitlement, credits(2))

  test("monthly booking spends nothing and keeps unlimited"):
    val (booked, debited, _) =
      book(
        id = BookingId(1),
        session = session(2),
        membership = monthly,
        member = alice,
        existing = Nil,
        now = before,
        log = Ledger.empty
      ).toOption.get
    assertEquals(booked.spent, Stamp.of(0).toOption.get)
    assertEquals(debited.entitlement, Entitlement.Unlimited)

  test("complimentary spends like packs"):
    val comp = Membership
      .of(
        id = MembershipId(7),
        user = alice,
        plan = PlanKind.Complimentary,
        startsOn = jan._1,
        endsOn = jan._2,
        entitlement = credits(5)
      )
      .toOption
      .get
    val (_, debited, _) =
      book(
        id = BookingId(1),
        session = session(2),
        membership = comp,
        member = alice,
        existing = Nil,
        now = before,
        log = Ledger.empty
      ).toOption.get
    assertEquals(debited.entitlement, credits(3))

  test("short balance refuses without spending"):
    val poor = pack(1)
    assertEquals(
      book(
        id = BookingId(1),
        session = session(2),
        membership = poor,
        member = alice,
        existing = Nil,
        now = before,
        log = Ledger.empty
      ),
      Left("insufficient credits")
    )
    // The refusal spent nothing: the single credit still books a cost-1 session.
    val (_, debited, _) =
      book(
        id = BookingId(2),
        session = session(1),
        membership = poor,
        member = alice,
        existing = Nil,
        now = before,
        log = Ledger.empty
      ).toOption.get
    assertEquals(debited.entitlement, credits(0))

  test("cancelled session refuses"):
    val closed =
      closeSession(session(2), Reason.of("room flooded").toOption.get, before)
    assertEquals(
      book(
        id = BookingId(1),
        session = closed,
        membership = pack(5),
        member = alice,
        existing = Nil,
        now = before,
        log = Ledger.empty
      ),
      Left("session is cancelled")
    )

  test("expired membership refuses"):
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
    assertEquals(
      book(
        id = BookingId(1),
        session = session(2),
        membership = old,
        member = alice,
        existing = Nil,
        now = before,
        log = Ledger.empty
      ),
      Left("membership is not currently valid")
    )

  test("another user's membership refuses"):
    assertEquals(
      book(
        id = BookingId(1),
        session = session(2),
        membership = pack(5, UserId(4)),
        member = alice,
        existing = Nil,
        now = before,
        log = Ledger.empty
      ),
      Left("membership belongs to another user")
    )

  test(
    "duplicate active booking refuses; cancelled prior booking frees the key"
  ):
    val first = book(
      id = BookingId(1),
      session = session(2),
      membership = pack(5),
      member = alice,
      existing = Nil,
      now = before,
      log = Ledger.empty
    ).toOption.get._1
    assertEquals(
      book(
        id = BookingId(2),
        session = session(2),
        membership = pack(5),
        member = alice,
        existing = List(first),
        now = before,
        log = Ledger.empty
      ),
      Left("duplicate booking")
    )
    val cancelled =
      first.copy(status = BookingStatus.Cancelled(Cancellation.OnTime(before)))
    assert(
      book(
        id = BookingId(2),
        session = session(2),
        membership = pack(5),
        member = alice,
        existing = List(cancelled),
        now = before,
        log = Ledger.empty
      ).isRight
    )

  test("late cancel refunds the stamp back to the balance"):
    val (booked1, debited, log1) =
      book(
        id = BookingId(1),
        session = session(2),
        membership = pack(5),
        member = alice,
        existing = Nil,
        now = before,
        log = Ledger.empty
      ).toOption.get
    assertEquals(debited.entitlement, credits(3))
    assertEquals(log1.balanceOf(MembershipId(7)), -2)
    val freePolicy =
      Policy
        .of(
          window = CancelWindow.of(Duration.ofHours(12)).toOption.get,
          enforcement = Enforcement.NoPenalty
        )
        .toOption
        .get
    val (_, record) =
      cancelMember(
        policy = freePolicy,
        venue = venue,
        start = start,
        now = before,
        booking = booked1,
        waiver = None
      )
    assertEquals(record.refunded, 2)
    assertEquals(debited.entitlement, credits(3))
    val (log2, restored) = settle(log1, record, debited, before)
    assertEquals(restored.entitlement, credits(5))
    assertEquals(log2.balanceOf(MembershipId(7)), 0)
    assertEquals(
      log2.entries,
      List(
        LedgerEntry(
          BookingId(1),
          MembershipId(7),
          2,
          LedgerReason.Refund,
          before
        ),
        LedgerEntry(
          BookingId(1),
          MembershipId(7),
          -2,
          LedgerReason.Spend,
          before
        )
      )
    )

  test("a strike refunds in full while still penalising"):
    val (booked1, debited, _) =
      book(
        id = BookingId(1),
        session = session(2),
        membership = pack(5),
        member = alice,
        existing = Nil,
        now = before,
        log = Ledger.empty
      ).toOption.get
    val strikePolicy =
      Policy
        .of(
          window = CancelWindow.of(Duration.ofHours(12)).toOption.get,
          enforcement = Enforcement.Strike
        )
        .toOption
        .get
    val (_, record) =
      cancelMember(
        policy = strikePolicy,
        venue = venue,
        start = start,
        now = before,
        booking = booked1,
        waiver = None
      )
    assertEquals(record.refunded, 2)
    assertEquals(
      record.status,
      BookingStatus.LateCancelled(
        Cancellation.LatePenalised(before, Enforcement.Strike)
      )
    )
    assertEquals(refund(debited.entitlement, record.refunded), credits(5))

  def credits(n: Int): Entitlement =
    Entitlement.Credits(CreditBalance.of(n).toOption.get)
