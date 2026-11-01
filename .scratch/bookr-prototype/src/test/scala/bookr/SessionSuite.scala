package bookr

import java.time.{Duration, Instant}

import Types.*

// Session lifecycle, asserted — not just demoed.
class SessionSuite extends munit.FunSuite:
  val venue = VenueId(OrgId(1), 2)
  val start = Instant.parse("2026-11-02T18:00:00Z")
  val before = Instant.parse("2026-11-02T10:00:00Z")
  val teacher = UserId(9)

  def session: Session =
    Session(SessionId(5), venue, teacher, start, 60, 15, None)
  def reason: Reason = Reason.of("room flooded").toOption.get
  def booking(id: Long): Booking =
    Booking(
      BookingId(id),
      UserId(3),
      SessionId(5),
      MembershipId(7),
      BookingStatus.Booked,
      Stamp.of(2).toOption.get
    )
  def policy: Policy =
    Policy
      .of(
        window = CancelWindow.of(Duration.ofHours(12)).toOption.get,
        enforcement = Enforcement.LoseCredit
      )
      .toOption
      .get

  test("endsAt derives from startsAt plus duration"):
    assertEquals(session.endsAt, start.plus(Duration.ofMinutes(60)))

  test("open session passes the booking guard"):
    assertEquals(requireOpen(session, before), Right(session))

  test("cancelled session is unbookable"):
    val closed = closeSession(session, reason, before)
    assertEquals(requireOpen(closed, before), Left("session is cancelled"))

  test("started session is unbookable"):
    assertEquals(
      requireOpen(session, start),
      Left("session has already started")
    )

  test("close stamps once; repeats keep the first stamp"):
    val once = closeSession(session, reason, before)
    val twice = closeSession(once, reason, before.plusSeconds(60))
    assertEquals(twice.cancelledAt, once.cancelledAt)

  test("close requires a non-blank reason"):
    assertEquals(Reason.of("  "), Left("reason is required"))

  test("provider cancel refunds every booking in full"):
    val closed = closeSession(session, reason, before)
    assert(closed.cancelledAt.isDefined)
    val results =
      List(booking(1), booking(2)).map(b =>
        cancelSession(policy, venue, start, before, b)
      )
    assert(results.forall { case (b, r) =>
      r.refunded == 2 && r.cause == Cause.SessionCancelled &&
      b.status == BookingStatus.Cancelled(Cancellation.LateAllowed(before))
    })

  test("desk cancels any session; teachers only their own"):
    val desk =
      List(RoleAssignment(UserId(7), Role.Frontdesk, Scope.AtVenue(venue)))
    val other = session.copy(teacher = UserId(8))
    assert(canCancelSession(desk, UserId(7), venue, other))
    assert(canCancelSession(Nil, teacher, venue, session))
    assert(!canCancelSession(Nil, teacher, venue, other))
    assert(!canCancelSession(Nil, UserId(3), venue, session))

  test("teacher pinned at the venue passes"):
    val roster =
      List(RoleAssignment(teacher, Role.Teacher, Scope.AtVenue(venue)))
    assertEquals(requireTeacherAtVenue(session, roster, venue), Right(session))

  test("org-wide teacher covers every venue"):
    val roster =
      List(RoleAssignment(teacher, Role.Teacher, Scope.OrgWide(OrgId(1))))
    assertEquals(requireTeacherAtVenue(session, roster, venue), Right(session))

  test("member named as teacher is refused"):
    val roster =
      List(RoleAssignment(teacher, Role.Member, Scope.AtVenue(venue)))
    assertEquals(
      requireTeacherAtVenue(session, roster, venue),
      Left("teacher holds no teacher role at the venue")
    )

  test("teacher role at another venue does not cover"):
    val elsewhere = VenueId(OrgId(1), 9)
    val roster =
      List(RoleAssignment(teacher, Role.Teacher, Scope.AtVenue(elsewhere)))
    assertEquals(
      requireTeacherAtVenue(session, roster, venue),
      Left("teacher holds no teacher role at the venue")
    )
