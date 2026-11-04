"""Waitlist promotion and hold-expiry sweep as shared tasks.

Eager locally and in CI (CELERY_EAGER=1); a worker/beat pair owns them in
prod. Both service functions are natural no-ops when there is nothing to
do, so retries and concurrent workers are safe.
"""

from celery import shared_task

from common.ids import SessionId


@shared_task(
    name="booking.promote_waitlist",
    autoretry_for=(Exception,),
    retry_backoff=True,
    max_retries=5,
)
def promote_waitlist(session_id: SessionId) -> int | None:
    from booking.services import promote_next
    from scheduling.models import ClassSession

    try:
        session = ClassSession.objects.get(pk=session_id)
    except ClassSession.DoesNotExist:
        return None
    promoted = promote_next(session)
    if promoted is None:
        return None
    return promoted.pk


@shared_task(
    name="booking.sweep_expired_holds",
    autoretry_for=(Exception,),
    retry_backoff=True,
    max_retries=5,
)
def sweep_expired_holds_task():
    from booking.services import sweep_expired_holds

    return sweep_expired_holds()
