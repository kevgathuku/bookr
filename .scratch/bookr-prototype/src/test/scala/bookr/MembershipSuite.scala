package bookr

import java.time.LocalDate

import Types.*

// Membership validity window + plan/entitlement coherence, asserted.
class MembershipSuite extends munit.FunSuite:
  val alice = UserId(3)
  val jan1 = LocalDate.of(2026, 1, 1)
  val jan31 = LocalDate.of(2026, 1, 31)
  val dec31 = LocalDate.of(2025, 12, 31)

  def credits(n: Int): Entitlement =
    Entitlement.Credits(CreditBalance.of(n).toOption.get)

  def monthly(
      id: Long,
      startsOn: LocalDate = jan1,
      endsOn: LocalDate = jan31
  ): Either[String, Membership] =
    Membership.of(
      id = MembershipId(id),
      user = alice,
      plan = PlanKind.Monthly,
      startsOn = startsOn,
      endsOn = endsOn,
      entitlement = Entitlement.Unlimited
    )

  test("ends_on before starts_on is rejected"):
    assertEquals(
      Membership.of(
        id = MembershipId(1),
        user = alice,
        plan = PlanKind.CreditPack,
        startsOn = jan31,
        endsOn = jan1,
        entitlement = credits(5)
      ),
      Left("end date is before start date")
    )

  test("monthly pairs only with unlimited"):
    assert(monthly(1).isRight)
    assertEquals(
      Membership.of(
        id = MembershipId(1),
        user = alice,
        plan = PlanKind.Monthly,
        startsOn = jan1,
        endsOn = jan31,
        entitlement = credits(5)
      ),
      Left("plan and entitlement disagree")
    )

  test("credit packs pair only with a balance"):
    assert(
      Membership
        .of(
          id = MembershipId(1),
          user = alice,
          plan = PlanKind.CreditPack,
          startsOn = jan1,
          endsOn = jan31,
          entitlement = credits(5)
        )
        .isRight
    )
    assertEquals(
      Membership.of(
        id = MembershipId(1),
        user = alice,
        plan = PlanKind.CreditPack,
        startsOn = jan1,
        endsOn = jan31,
        entitlement = Entitlement.Unlimited
      ),
      Left("plan and entitlement disagree")
    )

  test("complimentary plans spend a gratis balance like packs"):
    assert(
      Membership
        .of(
          id = MembershipId(1),
          user = alice,
          plan = PlanKind.Complimentary,
          startsOn = jan1,
          endsOn = jan31,
          entitlement = credits(5)
        )
        .isRight
    )

  test("active inside the window, boundaries inclusive"):
    val m = monthly(1).toOption.get
    assert(m.isActiveOn(jan1))
    assert(m.isActiveOn(jan31))
    assert(m.isActiveOn(LocalDate.of(2026, 1, 15)))

  test("booking on an expired plan is detectable"):
    val m = monthly(1).toOption.get
    assert(!m.isActiveOn(dec31))
    assert(!m.isActiveOn(LocalDate.of(2026, 2, 1)))
