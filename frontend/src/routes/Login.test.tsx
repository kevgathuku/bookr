import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AuthProvider } from "../auth";
import { VenueProvider } from "../venue";
import Login from "./Login";

function jsonResponse(body: unknown): Response {
	return new Response(JSON.stringify(body), {
		status: 200,
		headers: { "Content-Type": "application/json" },
	});
}

const MEMBER_ME = {
	id: 9,
	username: "member",
	memberships: [{ organization: "o", venue: "main", role: "member" }],
	venues: [
		{
			organization: "o",
			slug: "main",
			name: "Main",
			time_zone: "UTC",
		},
	],
};

function renderLogin() {
	const client = new QueryClient({
		defaultOptions: { queries: { retry: false } },
	});
	render(
		<QueryClientProvider client={client}>
			<VenueProvider>
				<AuthProvider>
					<MemoryRouter initialEntries={["/login"]}>
						<Routes>
							<Route path="/login" element={<Login />} />
							<Route path="/" element={<p>home</p>} />
						</Routes>
					</MemoryRouter>
				</AuthProvider>
			</VenueProvider>
		</QueryClientProvider>,
	);
}

describe("Login", () => {
	afterEach(() => {
		cleanup();
		vi.unstubAllGlobals();
		localStorage.clear();
	});

	it("shows the login card when logged out", async () => {
		vi.stubGlobal(
			"fetch",
			vi.fn(() => Promise.resolve(jsonResponse([]))),
		);
		renderLogin();

		await screen.findByTestId("login-button");
		expect(screen.getByTestId("username")).toBeInTheDocument();
	});

	it("redirects home when a session already exists", async () => {
		localStorage.setItem("bookr.refresh", "refresh-token");
		vi.stubGlobal(
			"fetch",
			vi.fn((url: string | URL | Request) => {
				if (String(url).endsWith("/api/v1/me/"))
					return Promise.resolve(jsonResponse(MEMBER_ME));
				return Promise.resolve(jsonResponse([]));
			}),
		);
		renderLogin();

		await screen.findByText("home");
		expect(screen.queryByTestId("username")).not.toBeInTheDocument();
	});
});
