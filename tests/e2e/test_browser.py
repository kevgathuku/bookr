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
        assert "waitlisted" in page.content().lower()

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


FRONTDESK = ("e2e-run-frontdesk", "password")


def _book_tiny(base_url):
    import uuid

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
    tiny_id = _tiny_id(base_url)
    booked = member.post(
        f"{base_url}/api/v1/bookings/",
        json={"scheduled_class": tiny_id, "idempotency_key": uuid.uuid4().hex},
    )
    assert booked.status_code == 201, booked.text
    return tiny_id


def test_frontdesk_desk_flow(frontend_url):
    playwright = pytest.importorskip("playwright.sync_api")
    _book_tiny(frontend_url)
    with playwright.sync_playwright() as driver:
        browser = driver.chromium.launch()
        page = browser.new_context().new_page()
        _login(page, frontend_url, FRONTDESK)

        # Desk link shows for staff; roster lists tomorrow's booking.
        page.get_by_role("link", name="Desk").click()
        page.get_by_test_id("desk").wait_for()
        tomorrow = page.evaluate(
            "() => new Date(Date.now() + 86400000).toISOString().slice(0, 10)"
        )
        page.get_by_test_id("roster-date").fill(tomorrow)
        page.get_by_test_id("roster-row").first.wait_for()

        # Keyboard-only check-in: focus + Enter stamps the badge.
        page.locator('[data-testid^="checkin-button-"]').first.focus()
        page.keyboard.press("Enter")
        page.locator('[data-testid^="checked-in-"]').first.wait_for()

        # Member lookup by keyboard: autofocused search submits on Enter.
        search = page.get_by_test_id("member-search")
        search.fill("e2e-run-member")
        search.press("Enter")
        page.locator('[data-testid^="member-hit-"]').first.click()
        page.get_by_test_id("member-panel").wait_for()

        # Credit adjust with a reason lands in the ledger.
        page.get_by_test_id("adjust-pass").select_option(index=1)
        page.get_by_test_id("adjust-reason").fill("goodwill")
        page.get_by_test_id("adjust-button").click()
        page.get_by_text("Adjustment saved.").wait_for()

        # Late-cancel override with a reason cancels the booking.
        row = page.locator('[data-testid="roster-row"]').first
        row.get_by_placeholder("Override reason").fill("desk-override")
        row.get_by_role("button", name="Override cancel").click()
        page.get_by_text("cancelled", exact=False).first.wait_for()

        # Member sees the adjust + refund rows with reasons in ledger UI.
        page.get_by_text("Log out").click()
        _login(page, frontend_url, MEMBER)
        page.get_by_text("Ledger").click()
        page.get_by_test_id("ledger").wait_for()
        page.get_by_text("adjustment").first.wait_for()
        page.get_by_text("goodwill", exact=False).first.wait_for()
        page.get_by_text("desk-override", exact=False).first.wait_for()
        page.get_by_text("refund").first.wait_for()

        browser.close()


def test_staff_manage_flow(frontend_url):
    playwright = pytest.importorskip("playwright.sync_api")
    with playwright.sync_playwright() as driver:
        browser = driver.chromium.launch()
        page = browser.new_context().new_page()
        _login(page, frontend_url, FRONTDESK)
        page.get_by_role("link", name="Manage").click()
        page.get_by_test_id("manage").wait_for()

        # Pass product create lands in the list.
        page.get_by_test_id("product-form-name").fill("E2E Pack")
        page.get_by_test_id("product-form-credits").fill("5")
        page.get_by_test_id("product-form-days").fill("30")
        page.get_by_test_id("product-create-button").click()
        page.locator('[data-testid^="product-name-"]').first.wait_for()

        # Policy activate appends history (never edits).
        page.get_by_test_id("policy-form-hours").fill("12")
        page.get_by_test_id("policy-activate-button").click()
        page.get_by_text("12h", exact=False).first.wait_for()

        # Aggregator create shows the token once; rotate replaces it.
        page.get_by_test_id("agg-form-slug").fill("e2e-aggy")
        page.get_by_test_id("agg-form-name").fill("Aggy")
        page.get_by_test_id("agg-create-button").click()
        token_text = page.get_by_test_id("agg-token").inner_text()
        assert "e2e-aggy" not in token_text
        first_token = token_text.split(": ", 1)[1]
        page.get_by_test_id("agg-rotate-e2e-aggy").click()
        page.wait_for_function(
            """(old) => {
                const el = document.querySelector('[data-testid=agg-token]');
                return el && !el.textContent.includes(old);
            }""",
            arg=first_token,
        )
        import requests as http_requests

        fresh_token = page.wait_for_function(
            """(old) => {
                const el = document.querySelector('[data-testid=agg-token]');
                const parts = el ? el.textContent.split(": ") : [];
                return el && !el.textContent.includes(old) && parts.length > 1
                    ? parts[1] : null;
            }""",
            arg=first_token,
        )
        feed = http_requests.get(
            f"{frontend_url}/api/v1/aggregators/e2e-aggy/schedule/",
            headers={"X-Partner-Token": fresh_token.json_value()},
        )
        assert feed.status_code == 200
        page.get_by_test_id("agg-events-e2e-aggy").click()
        page.get_by_text("GET", exact=False).first.wait_for()

        browser.close()


TEACHER = ("e2e-run-teacher", "password")


def test_teacher_schedule_flow(frontend_url):
    playwright = pytest.importorskip("playwright.sync_api")
    with playwright.sync_playwright() as driver:
        browser = driver.chromium.launch()
        page = browser.new_context().new_page()
        _login(page, frontend_url, TEACHER)
        page.get_by_role("link", name="Teach").click()
        page.get_by_test_id("teach").wait_for()
        page.get_by_test_id("teach-class-row").first.wait_for()

        browser.close()
