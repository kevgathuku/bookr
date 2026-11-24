"""Member, staff, and session cancel paths on tier cancellation rules.

Every cancel writes one immutable CancellationRecord pinning the full
context (session, member, plan, policy, actor, cause). Forgiveness never
rewrites history: inline waivers stamp the record at creation, retroactive
ones arrive as linked ledger adjustments. No fee path anywhere.
"""

import dataclasses
from datetime import datetime, timedelta
from typing import assert_never

from django.contrib.auth.models import User
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.db.models import F
from django.utils import timezone

from booking._core import (
    committed,
    get_session,
    load_open_booking,
    transition_booking,
)
from booking.errors import AlreadyCancelled, ConcurrentWrite, InvalidWaiver
from booking.models import (
    ACTIVE_STATUSES,
    Booking,
    CancellationPolicy,
    CancellationRecord,
)
from booking.notifications import notify_member_cancel, notify_session_cancelled
from booking.policies import resolve_policy
from booking.tasks import promote_waitlist
from common.ids import BookingId, OrgId, SessionId
from organizations.capabilities import (
    can_operate_desk,
    can_staff_door,
    can_waive,
    is_staff,
)
from organizations.models import Organization, OrgRole, Venue
from passes.models import CreditLedger, Membership
from scheduling.models import ClassSession


@dataclasses.dataclass(frozen=True)
class _Outcome:
    """One cancel decision: what applied, what moves, why."""

    applied: str
    refund: int
    cause: str
    status: str
    policy: CancellationPolicy | None
    on_behalf_of: bool
    reason: str


def cancel_booking(
    *,
    booking_id: BookingId,
    actor: User,
    on_behalf_of: bool = False,
    waive_penalty: bool = False,
    now: datetime | None = None,
    reason: str = "",
) -> CancellationRecord:
    """Cancel one booking, applying the resolved rule. Returns the record."""
    moment = now or timezone.now()
    with transaction.atomic():
        loaded = load_open_booking(BookingId(booking_id), moment)
        record = committed(
            _apply_cancel(
                booking=loaded.booking,
                session=loaded.session,
                venue=loaded.venue,
                organization=loaded.venue.organization,
                actor=actor,
                on_behalf_of=on_behalf_of,
                waive_penalty=waive_penalty,
                moment=moment,
                reason=reason,
            ),
            notify_member_cancel,
        )
        # A freed seat passes to the queue head (member, late, and
        # staff-on-behalf cancels all free exactly one seat here).
        promote_waitlist.delay(session_id=loaded.session.pk)
        return record


def _check_actor(
    *,
    actor: User,
    booking: Booking,
    organization: Organization,
    behalf: bool,
    waive: bool,
    reason: str,
) -> bool:
    owner = actor.pk == booking.member_id
    if not owner:
        _require_staff(actor=actor, organization=organization, reason=reason)
        _require_roster_or_desk(actor=actor, booking=booking, organization=organization)
    penalize = owner or behalf
    if waive:
        if not penalize:
            raise InvalidWaiver("waive_penalty with no penalty to waive.")
        _require_waiver(actor=actor, organization=organization, reason=reason)
    return penalize


def _require_roster_or_desk(
    *, actor: User, booking: Booking, organization: Organization
) -> None:
    # Desk roles cancel any booking; teachers only their own roster.
    teacher = booking.session.offering.teacher_id == actor.pk
    if not teacher and not can_operate_desk(
        _roles(actor=actor, organization=organization)
    ):
        raise PermissionDenied(
            "Teachers may only cancel bookings in classes they teach."
        )


def _apply_cancel(
    *,
    booking: Booking,
    session: ClassSession,
    venue: Venue,
    organization: Organization,
    actor: User,
    on_behalf_of: bool,
    waive_penalty: bool,
    moment: datetime,
    reason: str,
) -> CancellationRecord:
    penalize = _check_actor(
        actor=actor,
        booking=booking,
        organization=organization,
        behalf=on_behalf_of,
        waive=waive_penalty,
        reason=reason,
    )
    if booking.status == Booking.Status.HELD:
        # A held-but-unconfirmed seat releases as unclaimed regardless of
        # lateness or waiver: nothing was charged, so nothing is penalized.
        return release_unclaimed(
            booking=booking,
            session=session,
            organization=organization,
            actor=actor,
            reason=reason,
        )
    policy = resolve_policy(OrgId(organization.pk), booking.membership.plan.tier)
    late = moment > session.starts_at - timedelta(hours=policy.late_cancel_hours)
    stamp = booking.credits_spent
    outcome = member_outcome(
        policy=policy,
        late=late,
        penalize=penalize,
        waive_penalty=waive_penalty,
        stamp=stamp,
        on_behalf=on_behalf_of,
        reason=reason,
    )
    # Claim first: a concurrent writer loses here, before any refund hits
    # the ledger unique (the loser's INSERT would collide instead of lose).
    booking.status = outcome.status
    transition_booking(booking, status=outcome.status)
    if outcome.refund:
        _refund(
            booking=booking,
            amount=outcome.refund,
            actor=actor,
            note=outcome.reason,
        )
    return _write_record(
        booking=booking,
        session=session,
        organization=organization,
        outcome=outcome,
        actor=actor,
        late=late,
        waive_penalty=waive_penalty,
    )


def cancel_session(
    *, session_id: SessionId, actor: User, reason: str = ""
) -> list[CancellationRecord]:
    """Provider-side cancel: refund every active booking's stamp, penalize
    none. Repeat calls return the original records. The claim and the
    sweep share one transaction: a crash between them can never leave a
    cancelled session half-refunded, and the conditional claim makes
    concurrent calls and member-vs-session races safe."""
    if not reason:
        raise ValidationError("Session cancellations require a reason.")
    for _ in range(3):
        with transaction.atomic():
            session = get_session(SessionId(session_id))
            _require_session_cancel(
                actor=actor,
                organization=session.offering.venue.organization,
                session=session,
            )
            if session.cancelled_at is not None:
                # A concurrent cancel won but may not have committed its
                # records yet: spin until they land (bounded; an empty
                # return means the winner died mid-flight).
                for _ in range(100):
                    records = list(
                        CancellationRecord.objects.filter(
                            booking__session=session,
                            cause=CancellationRecord.Cause.SESSION_CANCELLED,
                        ).order_by("pk")
                    )
                    if records:
                        return records
                return records
            moment = timezone.now()
            claimed = ClassSession.objects.filter(
                pk=session.pk,
                version=session.version,
                cancelled_at__isnull=True,
            ).update(cancelled_at=moment, version=F("version") + 1)
            if not claimed:
                # A booking bump moved the version, not a second cancel:
                # re-read and decide again.
                continue
            session.cancelled_at = moment
            session.version += 1
            # None means a member cancel won that row: its record stands,
            # so the session sweep drops it instead of paying twice.
            records = list(
                filter(
                    None,
                    (
                        _cancel_one_for_session(
                            booking=booking,
                            session=session,
                            venue=session.offering.venue,
                            organization=session.offering.venue.organization,
                            actor=actor,
                        )
                        for booking in _live_session_bookings(session)
                    ),
                )
            )
            for record in records:
                committed(record, notify_session_cancelled)
            return records
    raise ConcurrentWrite("Session is under heavy contention; retry.")


def _live_session_bookings(session):
    return (
        session.bookings.filter(status__in=ACTIVE_STATUSES)
        .select_related("membership__plan")
        .order_by("pk")
    )


def mark_no_show(*, booking_id: BookingId, actor: User) -> CancellationRecord:
    """Door-observed absence: status flips, stamp stays spent, no strike."""
    with transaction.atomic():
        loaded = load_open_booking(
            BookingId(booking_id), timezone.now(), allow_started=True
        )
        booking, session = loaded.booking, loaded.session
        organization = loaded.venue.organization
        if session.starts_at > timezone.now():
            # No-show is observed absence. A future booking cannot be
            # absent, and the flip is irreversible — refuse the fat finger.
            raise ValidationError("Session has not started.")
        _require_door(actor=actor, organization=organization)
        if booking.status == Booking.Status.HELD:
            record = release_unclaimed(
                booking=booking,
                session=session,
                organization=organization,
                actor=actor,
                reason="",
            )
            promote_waitlist.delay(session_id=session.pk)
            return record
        booking.status = Booking.Status.NO_SHOW
        transition_booking(booking, status=booking.status)
        record = _write_no_show_record(
            booking=booking,
            session=session,
            organization=organization,
            actor=actor,
        )
        # The freed seat passes to the queue head.
        promote_waitlist.delay(session_id=session.pk)
        return record


def _write_no_show_record(
    *,
    booking: Booking,
    session: ClassSession,
    organization: Organization,
    actor: User,
) -> CancellationRecord:
    outcome = _Outcome(
        applied=CancellationPolicy.Enforcement.NONE,
        refund=0,
        cause=CancellationRecord.Cause.NO_SHOW,
        status=Booking.Status.NO_SHOW,
        policy=None,
        on_behalf_of=False,
        reason="",
    )
    return CancellationRecord.objects.create(
        booking=booking,
        member=booking.member,
        organization=organization,
        cause=outcome.cause,
        was_late=True,
        enforcement_applied=outcome.applied,
        credits_refunded=0,
        snapshot=_snapshot(
            booking=booking,
            session=session,
            outcome=outcome,
            actor=actor,
            waived=False,
        ),
    )


def check_in(*, booking_id: BookingId, actor: User) -> Booking:
    """Status-only attendance mark: no record, no money moves."""
    with transaction.atomic():
        loaded = load_open_booking(
            BookingId(booking_id), timezone.now(), allow_started=True
        )
        booking = loaded.booking
        organization = loaded.venue.organization
        if booking.status != Booking.Status.BOOKED:
            raise AlreadyCancelled("Only confirmed bookings can check in.")
        _require_door(actor=actor, organization=organization)
        booking.status = Booking.Status.ATTENDED
        booking.checked_in_at = timezone.now()
        transition_booking(
            booking, status=booking.status, checked_in_at=booking.checked_in_at
        )
        return booking


def waive_record(
    *,
    record_id: int,
    actor: User,
    reason: str = "",
) -> CreditLedger:
    """Retroactive waiver: a compensating ADJUSTMENT for forfeited credits,
    linked to the record. Idempotent per record; the record itself is never
    edited. Strike records carry no money, so there is nothing to
    compensate — forgive strikes inline at cancel time instead."""
    if not reason:
        raise ValidationError("Waiving a penalty requires a reason.")
    with transaction.atomic():
        record = CancellationRecord.objects.select_for_update().get(pk=record_id)
        _require_waiver(actor=actor, organization=record.organization, reason=reason)
        if (
            record.penalty_waived
            or record.enforcement_applied != CancellationPolicy.Enforcement.LOSE_CREDIT
        ):
            raise InvalidWaiver("Record carries no standing forfeit to waive.")
        owed = record.snapshot["credits_spent"] - record.credits_refunded
        if owed <= 0:
            # Monthly and comped seats forfeit nothing: no money moved,
            # so there is nothing to compensate (and zero-delta rows are
            # forbidden). Strike forgiveness is inline-only for the same
            # reason.
            raise InvalidWaiver("Record carries no standing forfeit to waive.")
        adjustment = CreditLedger.objects.filter(cancellation_record=record).first()
        if adjustment is None:
            from passes.services import post_entry

            membership = Membership.objects.get(
                pk=record.snapshot["membership_id"],
            )
            try:
                with transaction.atomic():
                    adjustment = post_entry(
                        membership,
                        owed,
                        CreditLedger.Reason.ADJUSTMENT,
                        booking=record.booking,
                        note=f"retroactive waiver of record #{record.pk}: {reason}",
                        created_by=actor,
                        cancellation_record=record,
                    )
            except IntegrityError:
                # Lost the race with a concurrent waiver: its row wins.
                # (Inner atomic above keeps this outer transaction usable.)
                adjustment = CreditLedger.objects.get(cancellation_record=record)
        return adjustment


def strike_count(
    member: User, organization: Organization, now: datetime | None = None
) -> int:
    """Stood STRIKE-enforcement lates in the rolling 30-day window.

    Inline-waived rows are excluded by flag; retroactively waived rows by
    their linked adjustment.
    """
    moment = now or timezone.now()
    waived_ids = CreditLedger.objects.filter(cancellation_record__isnull=False).values(
        "cancellation_record_id"
    )
    return (
        CancellationRecord.objects.filter(
            member=member,
            organization=organization,
            cause=CancellationRecord.Cause.MEMBER_CANCEL,
            was_late=True,
            enforcement_applied=CancellationPolicy.Enforcement.STRIKE,
            penalty_waived=False,
            created_at__gte=moment - timedelta(days=30),
        )
        .exclude(pk__in=waived_ids)
        .count()
    )


def release_unclaimed(
    *,
    booking: Booking,
    session: ClassSession,
    organization: Organization,
    actor: User | None,
    reason: str,
) -> CancellationRecord:
    """Shared exit for unconfirmed holds: never charged, so never
    penalized, refunded, or waived — released as unclaimed."""
    booking.status = Booking.Status.CANCELLED
    booking.hold_expires_at = None
    transition_booking(booking, status=booking.status, hold_expires_at=None)
    outcome = _Outcome(
        applied=CancellationPolicy.Enforcement.NONE,
        refund=0,
        cause=CancellationRecord.Cause.UNCLAIMED,
        status=Booking.Status.CANCELLED,
        policy=None,
        on_behalf_of=False,
        reason=reason,
    )
    return CancellationRecord.objects.create(
        booking=booking,
        member=booking.member,
        organization=organization,
        cause=outcome.cause,
        was_late=False,
        enforcement_applied=outcome.applied,
        credits_refunded=0,
        snapshot=_snapshot(
            booking=booking,
            session=session,
            outcome=outcome,
            actor=actor,
            waived=False,
        ),
    )


def _write_record(
    *,
    booking: Booking,
    session: ClassSession,
    organization: Organization,
    outcome: _Outcome,
    actor: User,
    late: bool,
    waive_penalty: bool,
) -> CancellationRecord:
    record = CancellationRecord.objects.create(
        booking=booking,
        member=booking.member,
        organization=organization,
        cause=outcome.cause,
        was_late=late,
        enforcement_applied=outcome.applied,
        penalty_waived=waive_penalty,
        waived_by=actor if waive_penalty else None,
        credits_refunded=outcome.refund,
        snapshot=_snapshot(
            booking=booking,
            session=session,
            outcome=outcome,
            actor=actor,
            waived=waive_penalty,
        ),
    )
    return record


def member_outcome(
    *,
    policy: CancellationPolicy,
    late: bool,
    penalize: bool,
    waive_penalty: bool,
    stamp: int,
    on_behalf: bool,
    reason: str,
) -> _Outcome:
    enforcement = CancellationPolicy.Enforcement(policy.enforcement)
    none = CancellationPolicy.Enforcement.NONE
    late_status = Booking.Status.LATE_CANCELLED
    member_cancel = CancellationRecord.Cause.MEMBER_CANCEL
    if not penalize:
        return _Outcome(
            none,
            stamp,
            CancellationRecord.Cause.STAFF_DECISION,
            Booking.Status.CANCELLED,
            policy,
            False,
            reason,
        )
    if not late or waive_penalty:
        status = late_status if late else Booking.Status.CANCELLED
        return _Outcome(none, stamp, member_cancel, status, policy, on_behalf, reason)
    if enforcement == CancellationPolicy.Enforcement.NONE:
        return _Outcome(
            none,
            stamp,
            member_cancel,
            late_status,
            policy,
            on_behalf,
            reason,
        )
    if enforcement == CancellationPolicy.Enforcement.LOSE_CREDIT:
        return _Outcome(
            enforcement,
            0,
            member_cancel,
            late_status,
            policy,
            on_behalf,
            reason,
        )
    if enforcement == CancellationPolicy.Enforcement.STRIKE:
        return _Outcome(
            enforcement,
            stamp,
            member_cancel,
            late_status,
            policy,
            on_behalf,
            reason,
        )
    assert_never(enforcement)


def _cancel_one_for_session(
    *,
    booking: Booking,
    session: ClassSession,
    venue: Venue,
    organization: Organization,
    actor: User,
) -> CancellationRecord | None:
    for _ in range(3):
        booking.status = Booking.Status.CANCELLED
        booking.hold_expires_at = None
        try:
            transition_booking(booking, status=booking.status, hold_expires_at=None)
        except AlreadyCancelled:
            booking.refresh_from_db()
            if booking.status not in ACTIVE_STATUSES:
                # A terminal transition won (member cancel, no-show,
                # check-in): its record stands, so the sweep skips the
                # row instead of paying twice.
                return None
            # Still live — a confirm landed first and charged the member:
            # fall through and re-claim the row so the sweep refunds it.
        else:
            break
    else:
        raise ConcurrentWrite("Session is under heavy contention; retry.")
    # Read after the claim: a confirm that landed mid-sweep changes what
    # is owed, and the refresh above already picked that up.
    stamp = booking.credits_spent
    if stamp:
        _refund(booking=booking, amount=stamp, actor=actor)
    policy = resolve_policy(OrgId(organization.pk), booking.membership.plan.tier)
    outcome = _Outcome(
        applied=CancellationPolicy.Enforcement.NONE,
        refund=stamp,
        cause=CancellationRecord.Cause.SESSION_CANCELLED,
        status=Booking.Status.CANCELLED,
        policy=policy,
        on_behalf_of=False,
        reason="",
    )
    return CancellationRecord.objects.create(
        booking=booking,
        member=booking.member,
        organization=organization,
        cause=outcome.cause,
        was_late=False,
        enforcement_applied=outcome.applied,
        credits_refunded=stamp,
        snapshot=_snapshot(
            booking=booking,
            session=session,
            outcome=outcome,
            actor=actor,
            waived=False,
        ),
    )


def _refund(*, booking: Booking, amount: int, actor: User, note: str = "") -> None:
    from passes.services import refund_for_booking

    membership = Membership.objects.get(pk=booking.membership_id)
    refund_for_booking(
        membership,
        amount,
        booking,
        created_by=actor,
        note=note,
    )


def _roles(*, actor: User, organization: Organization) -> set[str]:
    return set(
        OrgRole.objects.filter(user=actor, organization=organization).values_list(
            "role", flat=True
        )
    )


def _require_staff(*, actor: User, organization: Organization, reason: str) -> None:
    if not reason:
        raise ValidationError("Staff cancellations require a reason.")
    if not is_staff(_roles(actor=actor, organization=organization)):
        raise PermissionDenied("Staff only.")


def _require_session_cancel(
    *, actor: User, organization: Organization, session: ClassSession
) -> None:
    # Desk cancels any session; teachers cancel only the ones they teach.
    if can_operate_desk(_roles(actor=actor, organization=organization)):
        return
    if session.offering.teacher_id == actor.pk:
        return
    raise PermissionDenied("Front desk or the session's teacher only.")


def _require_door(*, actor: User, organization: Organization) -> None:
    if not can_staff_door(_roles(actor=actor, organization=organization)):
        raise PermissionDenied("Door staff only.")


def _require_waiver(*, actor: User, organization: Organization, reason: str) -> None:
    if not reason:
        raise ValidationError("Waiving a penalty requires a reason.")
    if not can_waive(_roles(actor=actor, organization=organization)):
        raise PermissionDenied("Waiving penalties requires the capability.")


def _snapshot(
    *,
    booking: Booking,
    session: ClassSession,
    outcome: _Outcome,
    actor: User | None,
    waived: bool,
) -> dict:
    snapshot = {
        "cause": outcome.cause,
        "session_id": session.pk,
        "session_starts_at": session.starts_at.isoformat(),
        "offering_title": session.offering.title,
        "class_category": session.offering.category,
        "venue_slug": session.offering.venue.slug,
        "organization_id": session.offering.venue.organization_id,
        "member_id": booking.member_id,
        "membership_id": booking.membership_id,
        "plan_type": booking.membership.plan.plan_type,
        "credits_spent": booking.credits_spent,
        "credits_refunded": outcome.refund,
        "policy": None,
        "actor_id": actor.pk if actor else None,
        "on_behalf_of": outcome.on_behalf_of,
        "reason": outcome.reason,
        # Duplicates the columns on purpose: the snapshot must tell the
        # whole outcome story without joining back to the row.
        "penalty_waived": waived,
        "waived_by_id": actor.pk if (waived and actor is not None) else None,
    }
    if outcome.policy is not None:
        snapshot["policy"] = {
            "id": outcome.policy.pk,
            "tier": outcome.policy.tier,
            "late_cancel_hours": outcome.policy.late_cancel_hours,
            "enforcement": outcome.policy.enforcement,
        }
    return snapshot
