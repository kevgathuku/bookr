import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AuthProvider } from "../auth";
import Schedule from "../routes/Schedule";
import { VenueProvider } from "../venue";

function jsonResponse(body: unknown, status = 200): Response {
	return new Response(JSON.stringify(body), {
		status,
		headers: { "Content-Type": "application/json" },
	});
}

function renderSchedule() {
	localStorage.setItem("bookr.venue", "main");
	const client = new QueryClient({
		defaultOptions: { queries: { retry: false } },
	});
	return render(
		<QueryClientProvider client={client}>
			<VenueProvider>
				<AuthProvider>
					<Schedule venue="main" />
				</AuthProvider>
			</VenueProvider>
		</QueryClientProvider>,
	);
}

describe("Schedule", () => {
	afterEach(() => {
		cleanup();
		vi.unstubAllGlobals();
		localStorage.clear();
	});

	it("books a class with one tap", async () => {
		const klass = {
			id: 7,
			class_type: 1,
			room: 1,
			teacher: 1,
			starts_at: new Date(Date.now() + 86400000).toISOString(),
			ends_at: new Date(Date.now() + 90000000).toISOString(),
			status: "scheduled",
			capacity: 20,
		};
		const fetchMock = vi
			.fn()
			.mockResolvedValueOnce(jsonResponse([klass]))
			.mockResolvedValueOnce(jsonResponse([]))
			.mockResolvedValueOnce(
				jsonResponse({ id: 9, status: "confirmed", scheduled_class: 7 }),
			);
		vi.stubGlobal("fetch", fetchMock);
		// crypto.randomUUID is available in jsdom; stub to be safe.
		if (!crypto.randomUUID) {
			vi.stubGlobal("crypto", { randomUUID: () => "uuid-1" });
		}
		renderSchedule();
		const user = userEvent.setup();

		await user.click(await screen.findByTestId(/book-button-/));

		await waitFor(() => {
			const [, init] = fetchMock.mock.calls[2] as [string, RequestInit];
			expect(JSON.parse(init.body as string).scheduled_class).toBe(7);
		});
	});

	it("offers the waitlist inline on 409", async () => {
		const klass = {
			id: 7,
			class_type: 1,
			room: 1,
			teacher: 1,
			starts_at: new Date(Date.now() + 86400000).toISOString(),
			ends_at: new Date(Date.now() + 90000000).toISOString(),
			status: "scheduled",
			capacity: 1,
		};
		const fetchMock = vi
			.fn()
			.mockResolvedValueOnce(jsonResponse([klass]))
			.mockResolvedValueOnce(jsonResponse([]))
			.mockResolvedValueOnce(new Response(null, { status: 409 }));
		vi.stubGlobal("fetch", fetchMock);
		renderSchedule();
		const user = userEvent.setup();

		await user.click(await screen.findByTestId(/book-button-/));

		await screen.findByTestId(/waitlist-button-/);
	});

	it("shows spots pills and groups classes by day", async () => {
		const noon = new Date();
		noon.setHours(12, 0, 0, 0);
		const dayA = new Date(noon.getTime() + 86400000);
		const dayB = new Date(noon.getTime() + 2 * 86400000);
		const classes = [
			{
				id: 1,
				class_type: 1,
				class_type_name: "Vinyasa",
				room: 1,
				room_name: "Studio A",
				teacher: 1,
				teacher_name: "Wanjiku",
				starts_at: dayA.toISOString(),
				ends_at: new Date(dayA.getTime() + 3600000).toISOString(),
				status: "scheduled",
				capacity: 20,
				spots_left: 8,
			},
			{
				id: 2,
				class_type: 1,
				class_type_name: "HIIT",
				room: 1,
				room_name: "Studio A",
				teacher: 2,
				teacher_name: "Otieno",
				starts_at: dayB.toISOString(),
				ends_at: new Date(dayB.getTime() + 3600000).toISOString(),
				status: "scheduled",
				capacity: 20,
				spots_left: 0,
			},
		];
		vi.stubGlobal(
			"fetch",
			vi
				.fn()
				.mockResolvedValueOnce(jsonResponse(classes))
				.mockResolvedValueOnce(jsonResponse([])),
		);
		renderSchedule();
		const user = userEvent.setup();

		expect(await screen.findByText("8 spots left")).toBeTruthy();
		expect(screen.getAllByTestId("class-row")).toHaveLength(1);

		const tabs = screen.getAllByRole("tab");
		await user.click(tabs[2]);
		expect(await screen.findByText("Full")).toBeTruthy();
		expect(screen.getAllByTestId("class-row")).toHaveLength(1);
		expect(screen.getByText("HIIT")).toBeTruthy();
	});
});
