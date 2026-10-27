import { afterEach, describe, expect, it, vi } from "vitest";
import {
	apiJson,
	clearAuth,
	setAccessToken,
	setRefreshToken,
} from "../api/client";

function jsonResponse(body: unknown, status = 200): Response {
	return new Response(JSON.stringify(body), {
		status,
		headers: { "Content-Type": "application/json" },
	});
}

describe("apiFetch refresh", () => {
	afterEach(() => {
		vi.unstubAllGlobals();
		localStorage.clear();
		clearAuth();
	});

	it("retries once after refresh on 401", async () => {
		setAccessToken("old-access");
		setRefreshToken("good-refresh");
		const fetchMock = vi
			.fn()
			.mockResolvedValueOnce(new Response(null, { status: 401 }))
			.mockResolvedValueOnce(
				jsonResponse({ access: "new-access", refresh: "new-refresh" }),
			)
			.mockResolvedValueOnce(jsonResponse({ ok: true }));
		vi.stubGlobal("fetch", fetchMock);

		const data = await apiJson<{ ok: boolean }>("/api/v1/me/");

		expect(data).toEqual({ ok: true });
		expect(fetchMock).toHaveBeenCalledTimes(3);
		const retry = fetchMock.mock.calls[2] as [string, RequestInit];
		expect(retry[1].headers).toMatchObject({});
		expect((retry[1].headers as Headers).get("Authorization")).toBe(
			"Bearer new-access",
		);
	});

	it("sends the venue header", async () => {
		localStorage.setItem("bookr.venue", "main");
		const fetchMock = vi.fn().mockResolvedValueOnce(jsonResponse([]));
		vi.stubGlobal("fetch", fetchMock);

		await apiJson("/api/v1/classes/");

		const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
		expect((init.headers as Headers).get("X-Venue-Slug")).toBe("main");
	});
});
