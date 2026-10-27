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
		if (path.includes("/substitutions/"))
			return Promise.resolve(
				jsonResponse([
					{
						id: 1,
						scheduled_class: 3,
						old_teacher: 7,
						old_teacher_name: "teacher",
						new_teacher: 9,
						new_teacher_name: "sub",
						reason: "sick",
						created_by: 1,
					},
				]),
			);
		if (path.includes("/calendar/")) return Promise.resolve(jsonResponse([]));
		return Promise.resolve(
			jsonResponse([
				{
					id: 3,
					class_type: 1,
					class_type_name: "Spin",
					room: 1,
					room_name: "A1",
					teacher: 7,
					teacher_name: "teacher",
					starts_at: new Date(Date.now() + 86400000).toISOString(),
					ends_at: new Date(Date.now() + 90000000).toISOString(),
					status: "scheduled",
					capacity: 20,
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

	it("shows my classes and my substitution history with names", async () => {
		localStorage.setItem("bookr.venue", "main");
		localStorage.setItem("bookr.refresh", "refresh-token");
		renderTeach();

		await screen.findByTestId("teach-class-row");
		expect(screen.getByText("Spin", { exact: false })).toBeInTheDocument();
		const sub = await screen.findByTestId("teach-sub-row");
		expect(sub.textContent).toContain("teacher → sub");
	});
});
