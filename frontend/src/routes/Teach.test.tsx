import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AuthProvider } from "../auth";
import { VenueProvider } from "../venue";
import Teach from "./Teach";

function jsonResponse(body: unknown, status = 200): Response {
	return new Response(JSON.stringify(body), {
		status,
		headers: { "Content-Type": "application/json" },
	});
}

const ME = {
	id: 7,
	username: "teacher",
	memberships: [{ organization: "o", venue: "main", role: "teacher" }],
	venues: [{ organization: "o", slug: "main", name: "Main", time_zone: "UTC" }],
};

function renderTeach() {
	const fetchMock = vi.fn((url: string | URL | Request) => {
		const path = String(url);
		if (path.endsWith("/api/v1/me/")) return Promise.resolve(jsonResponse(ME));
		return Promise.resolve(
			jsonResponse([
				{
					id: 3,
					venue: 1,
					offering: 1,
					offering_title: "Spin",
					category: "group",
					teacher: 7,
					teacher_name: "teacher",
					starts_at: new Date(Date.now() + 86400000).toISOString(),
					ends_at: new Date(Date.now() + 90000000).toISOString(),
					capacity: 20,
					spots_left: 19,
				},
			]),
		);
	});
	vi.stubGlobal("fetch", fetchMock);
	const client = new QueryClient({
		defaultOptions: { queries: { retry: false } },
	});
	return render(
		<QueryClientProvider client={client}>
			<VenueProvider>
				<AuthProvider>{<Teach />}</AuthProvider>
			</VenueProvider>
		</QueryClientProvider>,
	);
}

describe("Teach", () => {
	afterEach(() => {
		cleanup();
		vi.unstubAllGlobals();
		localStorage.clear();
	});

	it("shows my sessions with titles", async () => {
		localStorage.setItem("bookr.venue", "main");
		localStorage.setItem("bookr.refresh", "refresh-token");
		renderTeach();

		await screen.findByTestId("teach-class-row");
		expect(screen.getByText("Spin", { exact: false })).toBeInTheDocument();
	});
});
