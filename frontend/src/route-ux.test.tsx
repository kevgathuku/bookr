import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactElement } from "react";
import { Link, MemoryRouter, Route, Routes } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ErrorBoundary, NotFound, RouteFocus, SkeletonList } from "./route-ux";

function Thrower(): ReactElement {
	throw new Error("boom");
}

describe("route-ux", () => {
	afterEach(() => {
		vi.unstubAllGlobals();
	});

	it("skeleton announces busy loading", () => {
		render(<SkeletonList rows={2} />);

		expect(screen.getByLabelText("Loading")).toHaveAttribute(
			"aria-busy",
			"true",
		);
	});

	it("unknown route renders the 404 page with a way home", async () => {
		render(
			<MemoryRouter initialEntries={["/nowhere"]}>
				<Routes>
					<Route path="*" element={<NotFound />} />
				</Routes>
			</MemoryRouter>,
		);

		await screen.findByTestId("not-found");
		expect(screen.getByText("Back to schedule")).toBeInTheDocument();
	});

	it("error boundary catches and retries", async () => {
		const spy = vi.spyOn(console, "error").mockImplementation(() => {});
		render(
			<ErrorBoundary>
				<Thrower />
			</ErrorBoundary>,
		);
		const user = userEvent.setup();

		await screen.findByTestId("error-page");
		// Retry resets the boundary (child still throws → page again, no crash).
		await user.click(screen.getByText("Retry"));
		await screen.findByTestId("error-page");
		spy.mockRestore();
	});

	it("route change moves focus to main", async () => {
		render(
			<MemoryRouter initialEntries={["/a"]}>
				<RouteFocus>
					<Routes>
						<Route
							path="/a"
							element={
								<main>
									<h1>A</h1>
									<Link to="/b">Go</Link>
								</main>
							}
						/>
						<Route
							path="/b"
							element={
								<main>
									<h1>B</h1>
								</main>
							}
						/>
					</Routes>
				</RouteFocus>
			</MemoryRouter>,
		);
		const user = userEvent.setup();

		await user.click(screen.getByText("Go"));

		await screen.findByText("B");
		expect(document.activeElement?.tagName).toBe("MAIN");
	});
});
