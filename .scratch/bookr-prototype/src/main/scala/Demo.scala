package bookr

// Standard library only. Each section replaces a nullable column, a string,
// or a validation check with a type the compiler enforces.

import java.time.{Duration, Instant, LocalDate}

import Types.*

// ---------------------------------------------------------------------------
@main def demo(): Unit =
  val window = CancelWindow.of(Duration.ofHours(12)).toOption.get
  val home = VenueId(OrgId(1), 2)
  val fee = Enforcement.Fee(Money.of(1500).toOption.get)
  val policy = Policy
    .of(
      category = Some(SessionKind.Private),
      window = window,
      enforcement = fee
    )
    .toOption
    .get
  println(
    Policy.of(window = window, enforcement = fee)
  ) // Left: fee needs a private scope
  val general = Policy
    .of(window = window, enforcement = Enforcement.LoseCredit)
    .toOption
    .get
  val pinned = Policy
    .of(
      venue = Some(home),
      category = Some(SessionKind.Private),
      window = window,
      enforcement = fee
    )
    .toOption
    .get
  println(
    s"most specific wins -> ${Policy.resolve(List(general, pinned), home, SessionKind.Private, PlanKind.Monthly).enforcement}"
  )
  println(
    s"baseline covers empty rule sets -> ${Policy.resolve(Nil, VenueId(OrgId(1), 9), SessionKind.Group, PlanKind.CreditPack).enforcement}"
  )
  val start = Instant.parse("2026-11-02T18:00:00Z")

  val late =
    decide(policy, start, Instant.parse("2026-11-02T10:00:00Z"), home, None)
  println(s"late cancel under fee policy -> $late")
  println(s"fee owed on that cancellation -> ${lateFee(late)}")
  val spent = Stamp.of(2).toOption.get // credit_cost > 1: the stamp flows back
  val back = refundAmount(late, spent)
  println(
    s"booking spent ${spent.credits} credits, refunded $back" +
      " (a fee does not take the credits)"
  )
  println(
    s"balance Credits(3) + $back refunded = " +
      refund(Entitlement.Credits(CreditBalance.of(3).toOption.get), back)
  )

  val assignments = List(
    RoleAssignment(UserId(7), Role.Frontdesk, Scope.AtVenue(home))
  )

  val grant = WaiverAuthority.authorize(UserId(7), assignments, home)
  println(s"waiver grant for frontdesk -> $grant")
  val waiver = for
    g <- grant
    r <- Reason.of("teacher double-booked the room").toOption
  yield Waiver(g, r)
  val memberGrant = WaiverAuthority.authorize(UserId(9), assignments, home)
  println(
    s"waiver grant for plain member -> $memberGrant"
  ) // None: no waive rights

  val waived =
    decide(policy, start, Instant.parse("2026-11-02T10:00:00Z"), home, waiver)
  println(s"same cancel, waived by staff -> $waived")
  println(s"fee owed after waiver -> ${lateFee(waived)}")

  println(
    s"zero window (baseline) accepted -> ${CancelWindow.of(Duration.ZERO)}"
  )
  println(
    s"negative window rejected -> ${CancelWindow.of(Duration.ofHours(-1))}"
  )

  println(
    s"frontdesk of venue 2 waives at venue 2 -> " +
      can(assignments, UserId(7), home, Capability.WaivePenalty)
  )
  println(
    s"frontdesk of venue 2 waives at venue 3 -> " +
      can(assignments, UserId(7), VenueId(OrgId(1), 3), Capability.WaivePenalty)
  )
  println(
    s"frontdesk enters free at venue 2 -> " +
      isDutyStaff(assignments, UserId(7), home)
  )
  println(
    s"frontdesk operates door at venue 2 -> " +
      canOperateDoor(assignments, UserId(7), home)
  )
  val wide = List(
    RoleAssignment(UserId(7), Role.Manager, Scope.OrgWide(OrgId(1)))
  )
  println(
    s"org-wide manager enters free at home venue -> " +
      isDutyStaff(wide, UserId(7), home)
  )
  println(
    s"org-wide manager enters free at foreign venue -> " +
      isDutyStaff(wide, UserId(7), VenueId(OrgId(9), 3))
  ) // false: venue owns its org
  val lateAt = Instant.parse("2026-11-02T10:00:00Z")
  val booking = Booking(
    BookingId(1),
    UserId(3),
    SessionId(5),
    MembershipId(7),
    BookingStatus.Booked,
    spent
  )
  val demoMembership =
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
  val (flipped, memberRecord) =
    cancelMember(policy, home, start, lateAt, booking, None)
  println(
    s"member late cancel flips booking and writes one record -> $flipped / $memberRecord"
  )
  println(
    s"retroactive waiver of fee record -> ${reassess(memberRecord, demoMembership, home, waiver.get, lateAt, Ledger.empty)}"
  )
  val losePolicy = Policy
    .of(
      category = Some(SessionKind.Group),
      window = window,
      enforcement = Enforcement.LoseCredit
    )
    .toOption
    .get
  val forfeitBooking = booking.copy(id = BookingId(2))
  val (_, forfeit) =
    cancelMember(losePolicy, home, start, lateAt, forfeitBooking, None)
  println(s"member late lose-credit cancel -> $forfeit")
  println(
    s"retroactive waiver of forfeit -> ${reassess(forfeit, demoMembership, home, waiver.get, lateAt, Ledger.empty)}"
  )
  println(
    s"staff cancel flips booking and writes one record -> ${cancelStaff(policy, home, start, lateAt, booking)}"
  )
