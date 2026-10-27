import { describe, expect, it } from "vitest";
import { BOOK_ERROR_MESSAGE, bookErrorOf } from "../hooks";
import { calendarEventsForWeek } from "../routes/Calendar";
import { formatInVenueTimeZone, venueTimeZone } from "../venue";

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

	it("falls back to UTC on an unknown zone instead of crashing", () => {
		const text = formatInVenueTimeZone("2026-10-28T06:00:00Z", "Narnia/Nowhere");
		expect(text).toContain("06:00");
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
