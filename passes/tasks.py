from celery import shared_task


@shared_task(name="passes.expire_passes")
def expire_passes_task():
    from passes.services import expire_passes

    return expire_passes()
