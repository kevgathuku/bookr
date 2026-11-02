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

interface MockRoutes {
	me?: unknown;
	sessions?: unknown;
	bookings?: unknown;
	post?: { status: number; body?: unknown };
}

function mockApi(routes: MockRoutes) {
	localStorage.setItem("bookr.venue", "main");
	localStorage.setItem("bookr.refresh", "refresh-token");
	const fetchMock = vi.fn((url: string | URL | Request, init?: RequestInit) => {
		const path = String(url);
		if (path.endsWith("/api/v1/me/"))
			return Promise.resolve(jsonResponse(routes.me ?? MEMBER_ME));
		if (init?.method === "POST") {
			const post = routes.post ?? { status: 200, body: { id: 9 } };
			if (post.status === 200) return Promise.resolve(jsonResponse(post.body));
			return Promise.resolve(new Response(null, { status: post.status }));
		}
		if (path.includes("/api/v1/sessions/"))
			return Promise.resolve(jsonResponse(routes.sessions ?? []));
		if (path.includes("/api/v1/bookings/"))
			return Promise.resolve(jsonResponse(routes.bookings ?? []));
		return Promise.resolve(new Response(null, { status: 404 }));
	});
	vi.stubGlobal("fetch", fetchMock);
	return fetchMock;
}

function postBodies(fetchMock: { mock: { calls: unknown[][] } }): unknown[] {
	return fetchMock.mock.calls
		.filter((call) => (call[1] as RequestInit | undefined)?.method === "POST")
		.map((call) => JSON.parse((call[1] as RequestInit).body as string));
}

function renderSchedule() {
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

	it("books a session with one tap", async () => {
		const session = {
			id: 7,
			venue: 1,
			offering: 1,
			offering_title: "Spin",
			category: "group",
			teacher: 1,
			teacher_name: "Wanjiku",
			starts_at: new Date(Date.now() + 86400000).toISOString(),
			ends_at: new Date(Date.now() + 90000000).toISOString(),
			capacity: 20,
			spots_left: 19,
		};
		const fetchMock = mockApi({
			sessions: [session],
			bookings: [],
			post: { status: 200, body: { id: 9, status: "booked", session: 7 } },
		});
		renderSchedule();
		const user = userEvent.setup();

		await user.click(await screen.findByTestId(/book-button-/));

		await waitFor(() => {
			expect(postBodies(fetchMock)).toEqual([{ session: 7 }]);
		});
	});

	it("offers the waitlist inline on 409", async () => {
		const klass = {
			id: 7,
			venue: 1,
			offering: 1,
			offering_title: "Spin",
			category: "group",
			teacher: 1,
			teacher_name: "Wanjiku",
			starts_at: new Date(Date.now() + 86400000).toISOString(),
			ends_at: new Date(Date.now() + 90000000).toISOString(),
			capacity: 1,
			spots_left: 0,
		};
		const fetchMock = mockApi({
			sessions: [klass],
			bookings: [],
			post: { status: 409 },
		});
		renderSchedule();
		const user = userEvent.setup();

		await user.click(await screen.findByTestId(/book-button-/));

		await screen.findByTestId(/waitlist-button-/);
		expect(postBodies(fetchMock)).toEqual([{ session: 7 }]);
	});

	it("hides booking controls for a teacher without a member role", async () => {
		const klass = {
			id: 7,
			venue: 1,
			offering: 1,
			offering_title: "Spin",
			category: "group",
			teacher: 1,
			teacher_name: "Wanjiku",
			starts_at: new Date(Date.now() + 86400000).toISOString(),
			ends_at: new Date(Date.now() + 90000000).toISOString(),
			capacity: 20,
			spots_left: 19,
		};
		const teacherMe = {
			id: 7,
			username: "coach",
			memberships: [{ organization: "o", venue: null, role: "teacher" }],
			venues: [
				{
					organization: "o",
					slug: "main",
					name: "Main",
					time_zone: "UTC",
				},
			],
		};
		localStorage.setItem("bookr.refresh", "refresh-token");
		mockApi({ me: teacherMe, sessions: [klass], bookings: [] });
		renderSchedule();

		await screen.findByTestId("class-row");
		expect(screen.queryByTestId(/book-button-/)).not.toBeInTheDocument();
		expect(screen.queryByTestId(/waitlist-button-/)).not.toBeInTheDocument();
		expect(screen.queryByText("1 credit")).not.toBeInTheDocument();
		expect(screen.queryByText("Only bookable")).not.toBeInTheDocument();
	});

	it("shows spots pills and groups classes by day", async () => {
		const noon = new Date();
		noon.setHours(12, 0, 0, 0);
		const dayA = new Date(noon.getTime() + 86400000);
		const dayB = new Date(noon.getTime() + 2 * 86400000);
		const classes = [
			{
				id: 1,
				venue: 1,
				offering: 1,
				offering_title: "Vinyasa",
				category: "group",
				teacher: 1,
				teacher_name: "Wanjiku",
				starts_at: dayA.toISOString(),
				ends_at: new Date(dayA.getTime() + 3600000).toISOString(),
				capacity: 20,
				spots_left: 8,
			},
			{
				id: 2,
				venue: 1,
				offering: 2,
				offering_title: "HIIT",
				category: "group",
				teacher: 2,
				teacher_name: "Otieno",
				starts_at: dayB.toISOString(),
				ends_at: new Date(dayB.getTime() + 3600000).toISOString(),
				capacity: 20,
				spots_left: 0,
			},
		];
		mockApi({ sessions: classes, bookings: [] });
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
