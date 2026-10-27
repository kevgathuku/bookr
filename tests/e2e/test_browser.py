"""Browser journey (Playwright): login → book → full→waitlist as a second
member → waitlisted visible in bookings → venue switch re-fetches.

Runs against the live Django server serving the built SPA same-origin,
so API calls work with no proxy. Seeded e2e-run org provides both venues
and the capacity-1 Tiny class.
"""

import pytest
import requests

pytestmark = [pytest.mark.e2e, pytest.mark.django_db(transaction=True)]

MEMBER = ("e2e-run-member", "password")
BOOKER = ("e2e-run-booker", "password")


def _tiny_id(base_url):
    anonymous = requests.Session()
    token = anonymous.post(
        f"{base_url}/api/v1/auth/token/",
        json={"username": MEMBER[0], "password": MEMBER[1]},
    ).json()["access"]
    member = requests.Session()
    member.headers.update(
        {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
            "X-Venue-Slug": "main",
        }
    )
    classes = member.get(f"{base_url}/api/v1/classes/").json()
    tiny = [klass for klass in classes if klass["capacity"] == 1]
    assert tiny, "seed must provide the capacity-1 Tiny class"
    return tiny[0]["id"]


def _login(page, frontend_url, username, password):
    page.goto(frontend_url)
    page.get_by_test_id("username").fill(username)
    page.get_by_test_id("password").fill(password)
    page.get_by_test_id("login-button").click()
    page.get_by_test_id("schedule").wait_for()
    page.get_by_test_id("venue-switcher").select_option("main")


def test_member_journey(frontend_url):
    playwright = pytest.importorskip("playwright.sync_api")
    tiny_id = _tiny_id(frontend_url)
    with playwright.sync_playwright() as driver:
        browser = driver.chromium.launch()
        context = browser.new_context()
        page = context.new_page()

        # Member logs in and books the Tiny class (sole seat).
        _login(page, frontend_url, MEMBER[0], MEMBER[1])
        page.get_by_test_id(f"book-button-{tiny_id}").click()
        page.get_by_test_id("booked-badge").first.wait_for()

        # Booker finds it full, waitlists, sees it in bookings.
        page.get_by_text("Log out").click()
        _login(page, frontend_url, BOOKER[0], BOOKER[1])
        page.get_by_test_id(f"book-button-{tiny_id}").click()
        page.get_by_test_id(f"waitlist-button-{tiny_id}").click()
        page.get_by_text("My bookings").click()
        page.get_by_test_id("booking-row").first.wait_for()
        assert "waitlisted" in page.content()

        # Venue switch re-fetches (annex has one class, no badges).
        page.get_by_text("Schedule").click()
        page.get_by_test_id("venue-switcher").select_option("annex")
        page.get_by_test_id("schedule").wait_for()
        assert page.get_by_test_id("class-row").count() == 1

        browser.close()
