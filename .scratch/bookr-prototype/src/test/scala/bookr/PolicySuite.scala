package bookr

import java.time.{Duration, Instant, LocalDate}

import Types.*

// Fee enforcement: scope-gated at construction, non-consuming at cancel,
// non-compensable after the fact.
class PolicySuite extends munit.FunSuite:
  val venue = VenueId(OrgId(1), 2)
  val window = CancelWindow.of(Duration.ofHours(12)).toOption.get
  val start = Instant.parse("2026-11-02T18:00:00Z")
  val lateAt = Instant.parse("2026-11-02T10:00:00Z")
  val fee = Enforcement.Fee(Money.of(1500).toOption.get)

  def booking: Booking =
    Booking(
      id = BookingId(1),
      member = UserId(3),
      session = SessionId(5),
      membership = MembershipId(7),
      status = BookingStatus.Booked,
      spent = Stamp.of(2).toOption.get
    )

  def waiver: Waiver =
    val assignments =
      List(RoleAssignment(UserId(7), Role.Frontdesk, Scope.AtVenue(venue)))
    val grant = WaiverAuthority.authorize(UserId(7), assignments, venue).get
    val reason = Reason.of("teacher double-booked the room").toOption.get
    Waiver(grant, reason)

  def membership: Membership =
    Membership
      .of(
        id = MembershipId(7),
        user = UserId(3),
        plan = PlanKind.CreditPack,
        startsOn = LocalDate.of(2026, 1, 1),
        endsOn = LocalDate.of(2026, 12, 31),
        entitlement = Entitlement.Credits(CreditBalance.of(5).toOption.get)
      )
      .toOption
      .get

  test("fee requires a private category scope"):
    assert(
      Policy
        .of(
          category = Some(SessionKind.Private),
          window = window,
          enforcement = fee
        )
        .isRight
    )
    assertEquals(
      Policy.of(
        category = Some(SessionKind.Group),
        window = window,
        enforcement = fee
      ),
      Left("fee enforcement requires a private category scope")
    )
    assertEquals(
      Policy.of(window = window, enforcement = fee),
      Left("fee enforcement requires a private category scope")
    )
    assertEquals(
      Policy.of(
        category = Some(SessionKind.Workshop),
        window = window,
        enforcement = fee
      ),
      Left("fee enforcement requires a private category scope")
    )

  test("non-fee policies accept any scope"):
    assert(
      Policy
        .of(window = window, enforcement = Enforcement.LoseCredit)
        .isRight
    )
    assert(
      Policy
        .of(
          venue = Some(venue),
          category = Some(SessionKind.Group),
          plan = Some(PlanKind.Monthly),
          priority = 3,
          window = window,
          enforcement = Enforcement.Strike
        )
        .isRight
    )

  test("late fee penalises without consuming credits"):
    val policy =
      Policy
        .of(
          category = Some(SessionKind.Private),
          window = window,
          enforcement = fee
        )
        .toOption
        .get
    val (flipped, record) =
      cancelMember(policy, venue, start, lateAt, booking, None)
    assertEquals(record.refunded, 2)
    assertEquals(record.status, flipped.status)
    assertEquals(
      record.status,
      BookingStatus.LateCancelled(Cancellation.LatePenalised(lateAt, fee))
    )

  test("lateFee extracts the amount only from fee penalties"):
    assertEquals(
      lateFee(Cancellation.LatePenalised(lateAt, fee)),
      Some(Money.of(1500).toOption.get)
    )
    assertEquals(
      lateFee(Cancellation.LatePenalised(lateAt, Enforcement.LoseCredit)),
      None
    )
    assertEquals(lateFee(Cancellation.OnTime(lateAt)), None)
    assertEquals(lateFee(Cancellation.LateAllowed(lateAt)), None)
    assertEquals(
      lateFee(
        Cancellation.LateWaived(
          lateAt,
          waiver
        )
      ),
      None
    )

  test("retroactive waiver cannot compensate a fee record"):
    val policy =
      Policy
        .of(
          category = Some(SessionKind.Private),
          window = window,
          enforcement = fee
        )
        .toOption
        .get
    val (_, record) = cancelMember(
      policy = policy,
      venue = venue,
      start = start,
      now = lateAt,
      booking = booking,
      waiver = None
    )
    assertEquals(
      reassess(
        record = record,
        membership = membership,
        venue = venue,
        waiver = waiver,
        now = lateAt,
        log = Ledger.empty
      ),
      Left("record carries no compensable forfeit")
    )

  test("most-specific rule wins, including fee rules"):
    val general = Policy
      .of(window = window, enforcement = Enforcement.LoseCredit)
      .toOption
      .get
    val pinned = Policy
      .of(
        venue = Some(venue),
        category = Some(SessionKind.Private),
        window = window,
        enforcement = fee
      )
      .toOption
      .get
    assertEquals(
      Policy
        .resolve(
          List(general, pinned),
          venue,
          SessionKind.Private,
          PlanKind.Monthly
        )
        .enforcement,
      fee
    )
    assertEquals(
      Policy
        .resolve(
          List(general, pinned),
          venue,
          SessionKind.Group,
          PlanKind.Monthly
        )
        .enforcement,
      Enforcement.LoseCredit
    )

  test("baseline carries no penalty"):
    assertEquals(
      Policy
        .resolve(Nil, venue, SessionKind.Group, PlanKind.CreditPack)
        .enforcement,
      Enforcement.NoPenalty
    )
