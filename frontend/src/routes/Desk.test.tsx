import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AuthProvider } from "../auth";
import { VenueProvider } from "../venue";
import Desk from "./Desk";

function jsonResponse(body: unknown, status = 200): Response {
	return new Response(JSON.stringify(body), {
		status,
		headers: { "Content-Type": "application/json" },
	});
}

const ME = {
	username: "frontdesk",
	memberships: [],
	venues: [],
};

function renderDesk(fetchMock: ReturnType<typeof vi.fn>) {
	vi.stubGlobal("fetch", fetchMock);
	const client = new QueryClient({
		defaultOptions: { queries: { retry: false } },
	});
	return render(
		<QueryClientProvider client={client}>
			<VenueProvider>
				<AuthProvider>{<Desk />}</AuthProvider>
			</VenueProvider>
		</QueryClientProvider>,
	);
}

function deskFetch(
	roster: unknown[] = [],
	passes: unknown[] = [],
	doors: unknown[] = [],
) {
	return vi.fn((url: string | URL | Request, _init?: RequestInit) => {
		const path = String(url);
		if (path.endsWith("/api/v1/me/")) return Promise.resolve(jsonResponse(ME));
		if (path.includes("/bookings/roster/"))
			return Promise.resolve(jsonResponse(roster));
		if (path.includes("/passes/?member="))
			return Promise.resolve(jsonResponse(passes));
		if (path.includes("/members/search/"))
			return Promise.resolve(
				jsonResponse([{ id: 9, username: "sam-member" }]),
			);
		if (path.includes("/access/events/"))
			return Promise.resolve(jsonResponse(doors));
		if (path.includes("/checkin/"))
			return Promise.resolve(jsonResponse({ id: 1 }));
		if (path.includes("/ledger/adjust/"))
			return Promise.resolve(jsonResponse({ id: 2 }));
		return Promise.resolve(jsonResponse({}));
	});
}

describe("Desk", () => {
	afterEach(() => {
		cleanup();
		vi.unstubAllGlobals();
		localStorage.clear();
	});

	it("checks in a roster row with one tap", async () => {
		const fetchMock = deskFetch(
			[
				{
					id: 1,
					member: "sam",
					class_title: "Spin",
					starts_at: new Date().toISOString(),
					status: "confirmed",
					checked_in_at: null,
				},
			],
			[],
			[],
		);
		renderDesk(fetchMock);
		const user = userEvent.setup();

		await user.click(await screen.findByTestId("checkin-button-1"));

		await waitFor(() => {
			expect(
				fetchMock.mock.calls.some(
					([url]) => String(url).includes("/bookings/1/checkin/"),
				),
			).toBe(true);
		});
	});

	it("adjusts a member pass with a reason", async () => {
		const fetchMock = deskFetch(
			[],
			[
				{
					id: 4,
					product: 1,
					product_name: "Ten pack",
					credits_total: 10,
					credits_used: 2,
					valid_from: "2026-01-01",
					valid_until: null,
					status: "active",
				},
			],
			[],
		);
		renderDesk(fetchMock);
		const user = userEvent.setup();

		await user.click(await screen.findByTestId("member-search-button"));
		await user.click(await screen.findByTestId("member-hit-9"));
		await user.selectOptions(
			await screen.findByTestId("adjust-pass"),
			"4",
		);
		await user.type(screen.getByTestId("adjust-reason"), "goodwill");
		await user.click(screen.getByTestId("adjust-button"));

		await waitFor(() => {
			const call = fetchMock.mock.calls.find(([url]) =>
				String(url).includes("/ledger/adjust/"),
			);
			expect(call).toBeDefined();
			const init = call?.[1];
			const body = JSON.parse((init?.body ?? "") as string);
			expect(body).toMatchObject({
				member_pass: 4,
				delta: 1,
				reason: "goodwill",
			});
		});
	});
});
