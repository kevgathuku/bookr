import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import Schedule from "../routes/Schedule";

function jsonResponse(body: unknown, status = 200): Response {
	return new Response(JSON.stringify(body), {
		status,
		headers: { "Content-Type": "application/json" },
	});
}

function renderSchedule() {
	const client = new QueryClient({
		defaultOptions: { queries: { retry: false } },
	});
	return render(
		<QueryClientProvider client={client}>
			<Schedule venue="main" />
		</QueryClientProvider>,
	);
}

describe("Schedule", () => {
	afterEach(() => {
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
});
