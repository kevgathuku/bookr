import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";
import Claim from "./Claim";

function jsonResponse(body: unknown, status = 200): Response {
	return new Response(JSON.stringify(body), {
		status,
		headers: { "Content-Type": "application/json" },
	});
}

function renderClaim(entry = "/claim") {
	const fetchMock = vi.fn((_url: string | URL | Request) =>
		Promise.resolve(jsonResponse({ detail: "done" })),
	);
	vi.stubGlobal("fetch", fetchMock);
	render(
		<MemoryRouter initialEntries={[entry]}>
			<Claim />
		</MemoryRouter>,
	);
	return fetchMock;
}

describe("Claim", () => {
	afterEach(() => {
		cleanup();
		vi.unstubAllGlobals();
	});

	it("requests a claim link by email", async () => {
		const user = userEvent.setup();
		const fetchMock = renderClaim();

		await user.type(screen.getByTestId("claim-email"), "m@example.com");
		await user.click(screen.getByTestId("claim-request-button"));

		expect(fetchMock).toHaveBeenCalledOnce();
		const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
		expect(url).toBe("/api/v1/auth/password-reset/");
		expect(JSON.parse(init.body as string)).toEqual({
			email: "m@example.com",
		});
		expect(await screen.findByTestId("claim-sent")).toBeInTheDocument();
	});

	it("sets the password from a claim link", async () => {
		const user = userEvent.setup();
		const fetchMock = renderClaim("/claim?uid=abc&token=xyz");

		await user.type(screen.getByTestId("claim-password"), "s3cure-pass!");
		await user.type(
			screen.getByTestId("claim-password-confirm"),
			"s3cure-pass!",
		);
		await user.click(screen.getByTestId("claim-submit-button"));

		expect(fetchMock).toHaveBeenCalledOnce();
		const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
		expect(url).toBe("/api/v1/auth/password-reset-confirm/");
		expect(JSON.parse(init.body as string)).toEqual({
			uid: "abc",
			token: "xyz",
			new_password: "s3cure-pass!",
		});
		expect(await screen.findByTestId("claim-done")).toBeInTheDocument();
	});

	it("blocks mismatched passwords without calling the API", async () => {
		const user = userEvent.setup();
		const fetchMock = renderClaim("/claim?uid=abc&token=xyz");

		await user.type(screen.getByTestId("claim-password"), "s3cure-pass!");
		await user.type(
			screen.getByTestId("claim-password-confirm"),
			"other-pass!",
		);
		await user.click(screen.getByTestId("claim-submit-button"));

		expect(fetchMock).not.toHaveBeenCalled();
		expect(await screen.findByRole("alert")).toBeInTheDocument();
	});
});
