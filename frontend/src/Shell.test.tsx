import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AuthProvider } from "./auth";
import Shell from "./Shell";
import { VenueProvider } from "./venue";

function jsonResponse(body: unknown, status = 200): Response {
	return new Response(JSON.stringify(body), {
		status,
		headers: { "Content-Type": "application/json" },
	});
}

function meWith(role: string, venue: string | null) {
	return {
		id: 7,
		username: `${role}-user`,
		memberships: [{ organization: "o", venue, role }],
		venues: [
			{
				organization: "o",
				slug: "main",
				name: "Main",
				time_zone: "UTC",
			},
		],
	};
}

function renderShell(me: unknown) {
	localStorage.setItem("bookr.venue", "main");
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
					<MemoryRouter initialEntries={["/"]}>
						<Routes>
							<Route element={<Shell />}>
								<Route path="/" element={<p>home</p>} />
							</Route>
						</Routes>
					</MemoryRouter>
				</AuthProvider>
			</VenueProvider>
		</QueryClientProvider>,
	);
}

describe("Shell", () => {
	afterEach(() => {
		cleanup();
		vi.unstubAllGlobals();
		localStorage.clear();
	});

	it("shows only staff items to a manager without other roles", async () => {
		renderShell(meWith("manager", null));

		await screen.findByText("home");
		expect(screen.getByText("Schedule")).toBeInTheDocument();
		expect(screen.getByText("Calendar")).toBeInTheDocument();
		expect(screen.getByText("Desk")).toBeInTheDocument();
		expect(screen.getByText("Manage")).toBeInTheDocument();
		expect(screen.queryByText("Teach")).not.toBeInTheDocument();
		expect(screen.queryByText("My bookings")).not.toBeInTheDocument();
		expect(screen.queryByText("Passes")).not.toBeInTheDocument();
		expect(screen.queryByText("Ledger")).not.toBeInTheDocument();
		expect(screen.queryByText("Credits left")).not.toBeInTheDocument();
	});

	it("shows member items and no staff items to a member", async () => {
		renderShell(meWith("member", "main"));

		await screen.findByText("home");
		expect(screen.getByText("My bookings")).toBeInTheDocument();
		expect(screen.getByText("Passes")).toBeInTheDocument();
		expect(screen.getByText("Ledger")).toBeInTheDocument();
		expect(screen.queryByText("Teach")).not.toBeInTheDocument();
		expect(screen.queryByText("Desk")).not.toBeInTheDocument();
		expect(screen.queryByText("Manage")).not.toBeInTheDocument();
	});

	it("shows Teach to a teacher", async () => {
		renderShell(meWith("teacher", null));

		await screen.findByText("home");
		expect(screen.getByText("Teach")).toBeInTheDocument();
	});
});
