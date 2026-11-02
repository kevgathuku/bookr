import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AuthProvider } from "../auth";
import { BOOK_ERROR_MESSAGE, bookErrorOf } from "../hooks";
import { formatInVenueTimeZone, VenueProvider, venueTimeZone } from "../venue";
import Calendar, { calendarEventsForWeek } from "./Calendar";

function jsonResponse(body: unknown): Response {
	return new Response(JSON.stringify(body), {
		status: 200,
		headers: { "Content-Type": "application/json" },
	});
}

describe("calendarEventsForWeek", () => {
	it("maps API events to FullCalendar fields", () => {
		const mapped = calendarEventsForWeek([
			{
				kind: "class",
				id: 7,
				title: "Spin",
				starts_at: "2026-10-28T06:00:00Z",
				ends_at: "2026-10-28T07:00:00Z",
				room: "A1",
				teacher: 3,
			},
		]);
		expect(mapped).toEqual([
			{
				id: "7",
				title: "Spin",
				start: "2026-10-28T06:00:00Z",
				end: "2026-10-28T07:00:00Z",
				kind: "class",
			},
		]);
	});

	it("maps an empty week to no events", () => {
		expect(calendarEventsForWeek([])).toEqual([]);
		expect(calendarEventsForWeek(undefined)).toEqual([]);
	});
});

describe("venue time display", () => {
	it("prefers the venue time zone, UTC fallback", () => {
		const me = {
			venues: [{ slug: "main", time_zone: "Africa/Nairobi" }],
		};
		expect(venueTimeZone(me, "main")).toBe("Africa/Nairobi");
		expect(venueTimeZone(me, "annex")).toBe("UTC");
		expect(venueTimeZone(null, "main")).toBe("UTC");
	});

	it("renders UTC instants in venue time", () => {
		const text = formatInVenueTimeZone(
			"2026-10-28T06:00:00Z",
			"Africa/Nairobi",
		);
		expect(text).toContain("09:00");
	});

	it("throws on an unknown zone: validity is owned by the backend", () => {
		expect(() =>
			formatInVenueTimeZone("2026-10-28T06:00:00Z", "Narnia/Nowhere"),
		).toThrow();
	});
});

describe("empty week", () => {
	afterEach(() => {
		cleanup();
		vi.unstubAllGlobals();
		localStorage.clear();
	});

	it("keeps week navigation when there are no classes", async () => {
		const me = {
			id: 14,
			username: "coach",
			memberships: [{ organization: "o", venue: null, role: "teacher" }],
			venues: [
				{
					organization: "o",
					slug: "annex",
					name: "Annex",
					time_zone: "America/Chicago",
				},
			],
		};
		localStorage.setItem("bookr.venue", "annex");
		localStorage.setItem("bookr.refresh", "refresh-token");
		vi.stubGlobal(
			"fetch",
			vi.fn((url: string | URL | Request) => {
				if (String(url).endsWith("/api/v1/me/"))
					return Promise.resolve(jsonResponse(me));
				return Promise.resolve(jsonResponse([]));
			}),
		);
		const client = new QueryClient({
			defaultOptions: { queries: { retry: false } },
		});
		render(
			<QueryClientProvider client={client}>
				<VenueProvider>
					<AuthProvider>
						<MemoryRouter initialEntries={["/calendar"]}>
							<Routes>
								<Route path="/calendar" element={<Calendar />} />
							</Routes>
						</MemoryRouter>
					</AuthProvider>
				</VenueProvider>
			</QueryClientProvider>,
		);

		await screen.findByTitle("Previous week");
		expect(screen.queryByTitle("Next week")).toBeInTheDocument();
		expect(screen.queryByText("No classes this week.")).not.toBeInTheDocument();
	});
});

describe("bookErrorOf", () => {
	it("maps 409/402 to inline offers", () => {
		expect(bookErrorOf({ status: 409 })).toBe("full");
		expect(bookErrorOf({ status: 402 })).toBe("no-credits");
		expect(bookErrorOf({ status: 500 })).toBe("failed");
		expect(BOOK_ERROR_MESSAGE.full).toBe("Class is full.");
	});
});
