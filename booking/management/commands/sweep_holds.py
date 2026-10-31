"""Release lapsed waitlist holds (beat/cron calls this, not the web tier)."""

from django.core.management.base import BaseCommand

from booking.services import sweep_expired_holds


class Command(BaseCommand):
    help = "Cancel waitlist holds past their window; freed seats pass on."

    def handle(self, *args, **options):
        swept = sweep_expired_holds()
        self.stdout.write(self.style.SUCCESS(f"Released {swept} lapsed hold(s)."))
