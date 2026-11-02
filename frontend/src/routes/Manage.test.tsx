import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AuthProvider } from "../auth";
import { VenueProvider } from "../venue";
import Manage from "./Manage";

function jsonResponse(body: unknown, status = 200): Response {
	return new Response(JSON.stringify(body), {
		status,
		headers: { "Content-Type": "application/json" },
	});
}

const ME = { username: "owner", memberships: [], venues: [] };

function renderManage(fetchMock: ReturnType<typeof vi.fn>) {
	vi.stubGlobal("fetch", fetchMock);
	const client = new QueryClient({
		defaultOptions: { queries: { retry: false } },
	});
	return render(
		<QueryClientProvider client={client}>
			<VenueProvider>
				<AuthProvider>{<Manage />}</AuthProvider>
			</VenueProvider>
		</QueryClientProvider>,
	);
}

function manageFetch() {
	return vi.fn((url: string | URL | Request, _init?: RequestInit) => {
		const path = String(url);
		if (path.endsWith("/api/v1/me/")) return Promise.resolve(jsonResponse(ME));
		if (path.includes("/staff/aggregators/") && path.endsWith("/rotate/"))
			return Promise.resolve(
				jsonResponse({ slug: "gym", name: "Gym", api_token: "fresh-token" }),
			);
		if (path.includes("/staff/aggregators/"))
			return Promise.resolve(
				jsonResponse(
					path.includes("/events/")
						? [{ id: 1, method: "POST", path: "/x/", status_code: 201 }]
						: _init?.method === "POST"
							? { slug: "gym", name: "Gym", api_token: "shown-once" }
							: [],
				),
			);
		if (path.includes("/members/search/"))
			return Promise.resolve(jsonResponse([]));
		if (path.includes("/access/events/"))
			return Promise.resolve(jsonResponse([]));
		return Promise.resolve(
			jsonResponse({ slug: "gym", name: "Gym", api_token: "shown-once" }),
		);
	});
}

describe("Manage", () => {
	afterEach(() => {
		cleanup();
		vi.unstubAllGlobals();
		localStorage.clear();
	});

	it("shows the partner token exactly once on create", async () => {
		const fetchMock = manageFetch();
		renderManage(fetchMock);
		const user = userEvent.setup();

		await user.type(screen.getByTestId("agg-form-slug"), "gym");
		await user.type(screen.getByTestId("agg-form-name"), "Gym");
		await user.click(screen.getByTestId("agg-create-button"));

		await screen.findByTestId("agg-token");
		expect(screen.getByTestId("agg-token").textContent).toContain("shown-once");
		await waitFor(() => {
			const call = fetchMock.mock.calls.find(
				([url, init]) =>
					String(url).endsWith("/staff/aggregators/") &&
					(init as RequestInit)?.method === "POST",
			);
			expect(call).toBeDefined();
		});
	});
});
