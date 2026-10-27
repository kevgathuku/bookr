"""Browser specs (Playwright). Skip until the frontend preview exists —
the backend is API-only, so there is nothing to load yet. Frontend
tickets wire FRONTEND_URL + data-testid hooks (SPEC-frontend §5)."""

import pytest

pytestmark = [pytest.mark.e2e, pytest.mark.django_db(transaction=True)]


def test_schedule_renders(frontend_url):
    playwright = pytest.importorskip("playwright.sync_api")
    with playwright.sync_playwright() as driver:
        browser = driver.chromium.launch()
        page = browser.new_page()
        page.goto(frontend_url)
        page.get_by_test_id("schedule").wait_for()
        browser.close()
