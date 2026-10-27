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


def _login(page, frontend_url, credentials):
    username, password = credentials
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
        page = browser.new_context().new_page()

        # Member logs in and books the Tiny class (sole seat).
        _login(page, frontend_url, MEMBER)
        page.get_by_test_id(f"book-button-{tiny_id}").click()
        page.get_by_test_id("booked-badge").first.wait_for()

        # Booker finds it full, waitlists, sees it in bookings.
        page.get_by_text("Log out").click()
        _login(page, frontend_url, BOOKER)
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


def test_member_views_calendar_passes_ledger(frontend_url):
    playwright = pytest.importorskip("playwright.sync_api")
    with playwright.sync_playwright() as driver:
        browser = driver.chromium.launch()
        page = browser.new_context().new_page()
        _login(page, frontend_url, MEMBER)

        # Calendar renders the week's classes in venue time. FullCalendar
        # wraps events in a harness that intercepts pointer events, so the
        # event click uses force (real users click through without issue).
        page.get_by_text("Calendar").click()
        page.get_by_test_id("calendar").wait_for()
        page.locator(".fc-event").first.wait_for()
        page.locator(".fc-event").first.click(force=True)
        page.get_by_test_id("calendar-selection").wait_for()

        # Passes show remaining credits with expiry.
        page.get_by_text("Passes").click()
        page.get_by_test_id("passes").wait_for()
        page.get_by_test_id("pass-row").first.wait_for()
        assert "credits left" in page.content()

        # Ledger shows the seeded purchase with its reason.
        page.get_by_text("Ledger").click()
        page.get_by_test_id("ledger").wait_for()
        page.get_by_test_id("ledger-row").first.wait_for()
        assert "purchase" in page.content()

        browser.close()
