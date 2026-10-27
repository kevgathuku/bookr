from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APIClient

from organizations.models import Membership, Organization, Venue, VenuePolicy
from passes.models import PassProduct
from scheduling.models import ClassType, Room, ScheduledClass, TeacherSubstitution

pytestmark = pytest.mark.django_db

#  Staff gap-closure seam: everything SPEC implies but never names, all
#  staff-only, all venue-scoped (404 outside), all errors typed.
#  - substitution POST flips the class teacher + keeps the history row.
#  - pass-product POST/PATCH (no DELETE: issued passes PROTECT them).
#  - policy versions list + activate (retire+insert via the manager).
#  - pass grant (staff sale = pass + purchase ledger row).
#  - availability-slots (readable by members too: future booking flow).
#  Out of scope here by ticket ownership: aggregator CRUD (4je, Phase 2),
#  door-log read (8e5 owns the model).


def _user(username):
    return get_user_model().objects.create_user(username=username)


_ids = iter(range(1000000))


def _unique(username):
    return f"{username}-{next(_ids)}"


def _venue(slug="downtown"):
    org = Organization.objects.create(slug=f"org-{slug}", name=f"Org {slug}")
    return Venue.objects.create(organization=org, slug=slug, name=slug.title())


def _staff(venue, username="manager", role="manager"):
    user = _user(_unique(username))
    Membership.objects.create(
        organization=venue.organization, venue=venue, user=user, role=role
    )
    return user


def _member(venue, username="member"):
    user = _user(_unique(username))
    Membership.objects.create(
        organization=venue.organization,
        venue=venue,
        user=user,
        role=Membership.Role.MEMBER,
    )
    return user


def _class(venue, teacher=None):
    start = timezone.now() + timedelta(days=1)
    class_type, _ = ClassType.objects.get_or_create(
        venue=venue, name="Spin", defaults={"duration_min": 45}
    )
    room, _ = Room.objects.get_or_create(
        venue=venue, name="Studio", defaults={"capacity": 20}
    )
    return ScheduledClass.objects.create(
        venue=venue,
        class_type=class_type,
        room=room,
        teacher=teacher or _user(f"teacher-{venue.slug}"),
        starts_at=start,
        ends_at=start + timedelta(hours=1),
    )


def _client(user, slug="downtown"):
    client = APIClient()
    client.force_authenticate(user=user)
    client.defaults["HTTP_X_VENUE_SLUG"] = slug
    return client


class TestSubstitution:
    def test_post_flips_teacher_and_keeps_history(self):
        venue = _venue()
        old = _user("old-teacher")
        klass = _class(venue, teacher=old)
        new = _user("new-teacher")

        response = _client(_staff(venue)).post(
            "/api/v1/substitutions/",
            {"scheduled_class": klass.pk, "new_teacher": new.pk, "reason": "sick"},
        )

        assert response.status_code == 201
        assert response.json()["old_teacher_name"] == "old-teacher"
        assert response.json()["new_teacher_name"] == "new-teacher"
        klass.refresh_from_db()
        assert klass.teacher == new
        row = TeacherSubstitution.objects.get(scheduled_class=klass)
        assert (row.old_teacher, row.new_teacher) == (old, new)

    def test_same_teacher_rejected(self):
        venue = _venue()
        old = _user("old-teacher")
        klass = _class(venue, teacher=old)

        response = _client(_staff(venue)).post(
            "/api/v1/substitutions/",
            {"scheduled_class": klass.pk, "new_teacher": old.pk},
        )

        assert response.status_code == 400

    def test_member_forbidden_outsider_404(self):
        venue = _venue()
        klass = _class(venue)
        new = _user("new-teacher")
        payload = {"scheduled_class": klass.pk, "new_teacher": new.pk}

        assert (
            _client(_member(venue)).post("/api/v1/substitutions/", payload).status_code
            == 403
        )
        assert (
            _client(_member(venue), "nope")
            .post("/api/v1/substitutions/", payload)
            .status_code
            == 404
        )


class TestPassProduct:
    def test_create_and_patch(self):
        venue = _venue()
        client = _client(_staff(venue))

        created = client.post(
            "/api/v1/pass-products/",
            {
                "venue": venue.pk,
                "name": "Ten Pack",
                "credits_total": 10,
                "validity_days": 30,
            },
        )
        assert created.status_code == 201

        patched = client.patch(
            f"/api/v1/pass-products/{created.data['id']}/", {"credits_total": 20}
        )
        assert patched.status_code == 200
        assert patched.data["credits_total"] == 20

    def test_cross_venue_404(self):
        venue = _venue()
        other = _venue(slug="uptown")
        client = _client(_staff(venue), "uptown")

        response = client.post(
            "/api/v1/pass-products/",
            {"venue": other.pk, "name": "X", "credits_total": 5, "validity_days": 30},
        )

        assert response.status_code == 404


class TestPolicy:
    def test_list_versions(self):
        venue = _venue()
        VenuePolicy.objects.create(venue=venue)
        client = _client(_staff(venue))

        listed = client.get("/api/v1/policies/")

        assert listed.status_code == 200
        assert len(listed.data) == 1

    def test_activate(self):
        venue = _venue()
        VenuePolicy.objects.create(venue=venue)
        client = _client(_staff(venue))

        activated = client.post(
            "/api/v1/policies/activate/", {"class_late_cancel_hours": 12}
        )

        assert activated.status_code == 201
        assert activated.data["class_late_cancel_hours"] == 12
        assert VenuePolicy.objects.filter(venue=venue).count() == 2
        assert venue.current_policy.class_late_cancel_hours == 12

    def test_member_forbidden(self):
        venue = _venue()

        assert _client(_member(venue)).get("/api/v1/policies/").status_code == 403


class TestPassGrant:
    def test_grant_creates_pass_and_purchase_row(self):
        venue = _venue()
        product = PassProduct.objects.create(
            venue=venue, name="Ten Pack", credits_total=10, validity_days=30
        )
        member = _member(venue)
        client = _client(_staff(venue))

        response = client.post(
            "/api/v1/passes/grant/", {"member": member.pk, "product": product.pk}
        )

        assert response.status_code == 201
        assert response.data["credits_total"] == 10
        assert response.data["credits_used"] == 0

    def test_grant_foreign_product_404(self):
        venue = _venue()
        other = _venue(slug="uptown")
        product = PassProduct.objects.create(
            venue=other, name="Other Pack", credits_total=5, validity_days=30
        )
        member = _member(venue)

        response = _client(_staff(venue)).post(
            "/api/v1/passes/grant/", {"member": member.pk, "product": product.pk}
        )

        assert response.status_code == 404


class TestAvailabilitySlots:
    def test_member_can_read_slots(self):
        from scheduling.appointments import AvailabilityRule, Resource

        venue = _venue()
        resource = Resource.objects.create(
            venue=venue, name="Table", type=Resource.Kind.EQUIPMENT
        )
        AvailabilityRule.objects.create(
            resource=resource, weekday=0, start_time="09:00", end_time="10:00"
        )

        response = _client(_member(venue)).get(
            "/api/v1/availability/slots/",
            {"resource": resource.pk, "date": "2026-10-26", "duration": 60},
        )

        assert response.status_code == 200
        assert len(response.data) == 1

    def test_foreign_resource_404(self):
        venue = _venue()
        other = _venue(slug="uptown")
        from scheduling.appointments import Resource

        resource = Resource.objects.create(
            venue=other, name="Table", type=Resource.Kind.EQUIPMENT
        )

        response = _client(_staff(venue)).get(
            "/api/v1/availability/slots/",
            {"resource": resource.pk, "date": "2026-10-26", "duration": 60},
        )

        assert response.status_code == 404

    def test_bad_date_400(self):
        venue = _venue()
        from scheduling.appointments import Resource

        resource = Resource.objects.create(
            venue=venue, name="Table", type=Resource.Kind.EQUIPMENT
        )

        response = _client(_staff(venue)).get(
            "/api/v1/availability/slots/",
            {"resource": resource.pk, "date": "not-a-date", "duration": 60},
        )

        assert response.status_code == 400
