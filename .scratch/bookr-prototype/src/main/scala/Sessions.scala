package bookr

import java.time.{Duration, Instant}

import Types.*

// ---------------------------------------------------------------------------
// 10. Session lifecycle: cancelled or started sessions are unbookable;
//     provider cancel refunds every live booking and repeats idempotently.
// ---------------------------------------------------------------------------
final case class Session(
    id: SessionId,
    venue: VenueId,
    teacher: UserId,
    startsAt: Instant,
    durationMinutes: Int,
    capacity: Int,
    cancelledAt: Option[Instant]
):
  // End derives from start plus duration — never stored, so the two agree
  // the way ends_at agrees with the derived_end annotation.
  def endsAt: Instant = startsAt.plus(Duration.ofMinutes(durationMinutes))

// The booking-time guard: mirrors _ensure_open (cancelled rejects, and so
// does started — a session that began is no longer bookable).
def requireOpen(session: Session, now: Instant): Either[String, Session] =
  if session.cancelledAt.isDefined then Left("session is cancelled")
  else if !session.startsAt.isAfter(now) then
    Left("session has already started")
  else Right(session)

// Provider cancel: stamps cancelledAt once; repeats return the session
// untouched, so retries never re-stamp (mirrors the early return on
// already-cancelled sessions). Reason is required structurally but not
// stored — snapshots are unmodeled.
def closeSession(session: Session, reason: Reason, now: Instant): Session =
  session.cancelledAt match
    case Some(_) => session
    case None    => session.copy(cancelledAt = Some(now))
