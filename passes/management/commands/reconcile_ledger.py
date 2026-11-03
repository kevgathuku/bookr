"""Report memberships whose cached balance drifted from the ledger sum.

The ledger is the source of truth; credits_remaining is a cache updated
in the same transaction by post_entry(). Any mismatch means a writer
bypassed the choke-point. Unlimited memberships (NULL balance) are
skipped: they hold no rows by construction.
"""

from django.core.management.base import BaseCommand, CommandError
from django.db.models import Sum

from passes.models import CreditLedger, Membership


class Command(BaseCommand):
    help = "Fail when a cached credit balance disagrees with its ledger sum."

    def handle(self, *args, **options):
        sums = dict(
            CreditLedger.objects.values("membership_id")
            .annotate(
                total=Sum("delta"),
            )
            .values_list("membership_id", "total"),
        )
        drifted = []
        for membership_id, cached in Membership.objects.filter(
            credits_remaining__isnull=False,
        ).values_list("id", "credits_remaining"):
            if sums.get(membership_id, 0) != cached:
                drifted.append((membership_id, cached, sums.get(membership_id, 0)))
        if drifted:
            for membership_id, cached, actual in drifted:
                self.stderr.write(
                    f"membership {membership_id}: cache={cached} ledger={actual}",
                )
            raise CommandError(f"{len(drifted)} memberships drifted from the ledger.")
        self.stdout.write("Ledger and caches agree.")
