import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AuthProvider } from "../auth";
import Ledger from "../routes/Ledger";
import Passes from "../routes/Passes";
import { VenueProvider } from "../venue";

function jsonResponse(body: unknown, status = 200): Response {
	return new Response(JSON.stringify(body), {
		status,
		headers: { "Content-Type": "application/json" },
	});
}

function renderWithProviders(route: "passes" | "ledger") {
	const client = new QueryClient({
		defaultOptions: { queries: { retry: false } },
	});
	return render(
		<QueryClientProvider client={client}>
			<VenueProvider>
				<AuthProvider>
					{route === "passes" ? <Passes /> : <Ledger />}
				</AuthProvider>
			</VenueProvider>
		</QueryClientProvider>,
	);
}

describe("empty states", () => {
	afterEach(() => {
		vi.unstubAllGlobals();
		localStorage.clear();
	});

	it("passes explains where to buy one", async () => {
		vi.stubGlobal("fetch", vi.fn().mockResolvedValueOnce(jsonResponse([])));
		renderWithProviders("passes");

		await screen.findByText("No passes yet. Buy one at the front desk.");
	});

	it("ledger explains the quiet", async () => {
		vi.stubGlobal("fetch", vi.fn().mockResolvedValueOnce(jsonResponse([])));
		renderWithProviders("ledger");

		await screen.findByText("No credit movements yet.");
	});

	it("ledger renders amounts with reasons in venue time", async () => {
		localStorage.setItem("bookr.venue", "main");
		localStorage.setItem("bookr.refresh", "refresh-token");
		const fetchMock = vi.fn((url: string | URL | Request) => {
			if (String(url).endsWith("/api/v1/me/")) {
				return Promise.resolve(
					jsonResponse({
						username: "member",
						memberships: [],
						venues: [
							{
								organization: "o",
								slug: "main",
								name: "Main",
								time_zone: "UTC",
							},
						],
					}),
				);
			}
			return Promise.resolve(
				jsonResponse([
					{
						id: 1,
						member_pass: 2,
						booking: 3,
						delta: -1,
						reason: "adjustment",
						note: "goodwill",
						created_by: null,
						created_at: "2026-10-28T06:00:00Z",
					},
				]),
			);
		});
		vi.stubGlobal("fetch", fetchMock);
		renderWithProviders("ledger");

		await screen.findByTestId("ledger-row");
		expect(screen.getByText("adjustment")).toBeInTheDocument();
		expect(
			screen.getByText("— goodwill", { exact: false }),
		).toBeInTheDocument();
		expect(screen.getByText("-1")).toBeInTheDocument();
	});
});
