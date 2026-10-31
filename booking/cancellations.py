"""Member, staff, and session cancel paths on scoped cancellation rules.

Every cancel writes one immutable CancellationRecord pinning the full
context (session, member, plan, policy, actor, cause). Forgiveness never
rewrites history: inline waivers stamp the record at creation, retroactive
ones arrive as linked ledger adjustments. No fee path anywhere.
"""

import dataclasses
from datetime import timedelta

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from booking.errors import AlreadyCancelled, InvalidWaiver, SessionStarted
from booking.models import (
    ACTIVE_STATUSES,
    Booking,
    CancellationPolicy,
    CancellationRecord,
)
from booking.policies import resolve_policy
from organizations.capabilities import (
    can_operate_desk,
    can_staff_door,
    can_waive,
)
from organizations.models import OrgRole
from passes.models import CreditLedger, Membership
from scheduling.catalogue import ClassSession


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
    booking_id,
    actor,
    on_behalf_of=False,
    waive_penalty=False,
    now=None,
    reason="",
):
    """Cancel one booking, applying the resolved rule. Returns the record."""
    moment = now or timezone.now()
    with transaction.atomic():
        booking, session, venue, organization = _load_open_booking(booking_id, moment)
        return _apply_cancel(
            booking,
            session,
            venue,
            organization,
            actor,
            on_behalf_of,
            waive_penalty,
            moment,
            reason,
        )


def _check_actor(actor, booking, organization, behalf, waive, reason):
    owner = actor.pk == booking.member_id
    if not owner:
        _require_staff(actor, organization, reason)
        _require_roster_or_desk(actor, booking, organization)
    penalize = owner or behalf
    if waive:
        if not penalize:
            raise InvalidWaiver("waive_penalty with no penalty to waive.")
        _require_waiver(actor, organization, reason)
    return penalize


def _require_roster_or_desk(actor, booking, organization):
    # Desk roles cancel any booking; teachers only their own roster.
    teacher = booking.session.offering.teacher_id == actor.pk
    if not teacher and not can_operate_desk(_roles(actor, organization)):
        raise PermissionDenied(
            "Teachers may only cancel bookings in classes they teach."
        )


def _apply_cancel(
    booking,
    session,
    venue,
    organization,
    actor,
    on_behalf_of,
    waive_penalty,
    moment,
    reason,
):
    penalize = _check_actor(
        actor, booking, organization, on_behalf_of, waive_penalty, reason
    )
    policy = resolve_policy(
        organization.pk,
        venue.pk,
        session.offering.category,
        booking.membership.plan.plan_type,
    )
    late = moment > session.starts_at - timedelta(hours=policy.late_cancel_hours)
    stamp = booking.credits_spent
    outcome = _member_outcome(
        policy, late, penalize, waive_penalty, stamp, on_behalf_of, reason
    )
    booking.status = outcome.status
    if outcome.refund:
        _refund(booking, outcome.refund, actor)
    return _write_record(
        booking, session, organization, outcome, actor, late, waive_penalty
    )


def cancel_session(*, session_id, actor, reason=""):
    """Provider-side cancel: refund every active booking's stamp, penalize
    none. Repeat calls return the original records; the row lock makes
    concurrent calls and member-vs-session races safe."""
    if not reason:
        raise ValidationError("Session cancellations require a reason.")
    with transaction.atomic():
        session = ClassSession.objects.select_for_update().get(pk=session_id)
        venue = session.offering.venue
        organization = venue.organization
        _require_session_cancel(actor, organization, session)
        if session.cancelled_at is not None:
            return list(
                CancellationRecord.objects.filter(
                    booking__session=session,
                    cause=CancellationRecord.Cause.SESSION_CANCELLED,
                ).order_by("pk")
            )
        session.cancelled_at = timezone.now()
        session.save(update_fields=["cancelled_at"])
        bookings = (
            session.bookings.filter(status__in=ACTIVE_STATUSES)
            .select_for_update()
            .select_related("membership__plan")
            .order_by("pk")
        )
        return [
            _cancel_one_for_session(booking, session, venue, organization, actor)
            for booking in bookings
        ]


def mark_no_show(*, booking_id, actor):
    """Door-observed absence: status flips, stamp stays spent, no strike."""
    with transaction.atomic():
        booking, session, _venue, organization = _load_open_booking(
            booking_id, timezone.now(), allow_started=True
        )
        if session.starts_at > timezone.now():
            # No-show is observed absence. A future booking cannot be
            # absent, and the flip is irreversible — refuse the fat finger.
            raise ValidationError("Session has not started.")
        _require_door(actor, organization)
        booking.status = Booking.Status.NO_SHOW
        booking.save(update_fields=["status"])
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
            snapshot=_snapshot(booking, session, outcome, actor),
        )


def check_in(*, booking_id, actor):
    """Status-only attendance mark: no record, no money moves."""
    with transaction.atomic():
        booking, _session, _venue, organization = _load_open_booking(
            booking_id, timezone.now(), allow_started=True
        )
        _require_door(actor, organization)
        booking.status = Booking.Status.ATTENDED
        booking.save(update_fields=["status"])
        return booking


def waive_record(*, record_id, actor, reason=""):
    """Retroactive waiver: a compensating ADJUSTMENT for forfeited credits,
    linked to the record. Idempotent per record; the record itself is never
    edited. Strike records carry no money, so there is nothing to
    compensate — forgive strikes inline at cancel time instead."""
    if not reason:
        raise ValidationError("Waiving a penalty requires a reason.")
    with transaction.atomic():
        record = CancellationRecord.objects.select_for_update().get(pk=record_id)
        _require_waiver(actor, record.organization, reason)
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
        adjustment, created = CreditLedger.objects.get_or_create(
            cancellation_record=record,
            defaults={
                "membership_id": record.snapshot["membership_id"],
                "booking": record.booking,
                "delta": owed,
                "reason": CreditLedger.Reason.ADJUSTMENT,
                "note": f"retroactive waiver of record #{record.pk}: {reason}",
                "created_by": actor,
            },
        )
        if created:
            locked = Membership.objects.select_for_update().get(
                pk=adjustment.membership_id
            )
            locked.credits_remaining += owed
            locked.save(update_fields=["credits_remaining"])
        return adjustment


def strike_count(member, organization, now=None):
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


def _load_open_booking(booking_id, moment, allow_started=False):
    booking = (
        Booking.objects.select_for_update()
        .select_related("session__offering__venue", "membership__plan", "member")
        .get(pk=booking_id)
    )
    session = booking.session
    if booking.status != Booking.Status.BOOKED:
        raise AlreadyCancelled("Booking is no longer active.")
    if session.cancelled_at is not None:
        raise SessionStarted("Session has been cancelled.")
    started = session.starts_at <= moment
    if started and not allow_started:
        raise SessionStarted(
            "Session has already started; record attendance with no-show."
        )
    venue = session.offering.venue
    return booking, session, venue, venue.organization


def _write_record(booking, session, organization, outcome, actor, late, waive_penalty):
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
        snapshot=_snapshot(booking, session, outcome, actor),
    )
    booking.save(update_fields=["status"])
    return record


def _member_outcome(policy, late, penalize, waive_penalty, stamp, on_behalf, reason):
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
    if not late or policy.enforcement == none or waive_penalty:
        status = late_status if late else Booking.Status.CANCELLED
        return _Outcome(none, stamp, member_cancel, status, policy, on_behalf, reason)
    if policy.enforcement == CancellationPolicy.Enforcement.LOSE_CREDIT:
        return _Outcome(
            policy.enforcement,
            0,
            member_cancel,
            late_status,
            policy,
            on_behalf,
            reason,
        )
    return _Outcome(
        policy.enforcement,
        stamp,
        member_cancel,
        late_status,
        policy,
        on_behalf,
        reason,
    )


def _cancel_one_for_session(booking, session, venue, organization, actor):
    stamp = booking.credits_spent
    booking.status = Booking.Status.CANCELLED
    booking.save(update_fields=["status"])
    if stamp:
        _refund(booking, stamp, actor)
    policy = resolve_policy(
        organization.pk,
        venue.pk,
        session.offering.category,
        booking.membership.plan.plan_type,
    )
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
        snapshot=_snapshot(booking, session, outcome, actor),
    )


def _refund(booking, amount, actor):
    # Lock the membership: two concurrent cancels refunding the same
    # member must serialize, or one credit-back is silently lost.
    membership = Membership.objects.select_for_update().get(pk=booking.membership_id)
    membership.credits_remaining += amount
    membership.save(update_fields=["credits_remaining"])
    CreditLedger.objects.create(
        membership=membership,
        booking=booking,
        delta=amount,
        reason=CreditLedger.Reason.REFUND,
        created_by=actor,
    )


def _roles(actor, organization):
    return set(
        OrgRole.objects.filter(user=actor, organization=organization).values_list(
            "role", flat=True
        )
    )


def _require_staff(actor, organization, reason):
    if not reason:
        raise ValidationError("Staff cancellations require a reason.")
    if (
        not OrgRole.objects.filter(user=actor, organization=organization)
        .exclude(role=OrgRole.Role.MEMBER)
        .exists()
    ):
        raise PermissionDenied("Staff only.")


def _require_session_cancel(actor, organization, session):
    # Desk cancels any session; teachers cancel only the ones they teach.
    if can_operate_desk(_roles(actor, organization)):
        return
    if session.offering.teacher_id == actor.pk:
        return
    raise PermissionDenied("Front desk or the session's teacher only.")


def _require_door(actor, organization):
    if not can_staff_door(_roles(actor, organization)):
        raise PermissionDenied("Door staff only.")


def _require_waiver(actor, organization, reason):
    if not reason:
        raise ValidationError("Waiving a penalty requires a reason.")
    if not can_waive(_roles(actor, organization)):
        raise PermissionDenied("Waiving penalties requires the capability.")


def _snapshot(booking, session, outcome, actor):
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
        "actor_id": actor.pk,
        "on_behalf_of": outcome.on_behalf_of,
        "reason": outcome.reason,
    }
    if outcome.policy is not None:
        snapshot["policy"] = {
            "id": outcome.policy.pk,
            "specificity": outcome.policy.specificity,
            "priority": outcome.policy.priority,
            "late_cancel_hours": outcome.policy.late_cancel_hours,
            "enforcement": outcome.policy.enforcement,
        }
    return snapshot
