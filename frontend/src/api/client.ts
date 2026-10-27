/** Base fetch: same-origin API, Bearer auth + venue header, refresh-once on 401. */

const REFRESH_KEY = "bookr.refresh";

let accessToken: string | null = null;

export function setAccessToken(token: string | null): void {
	accessToken = token;
}

export function getRefreshToken(): string | null {
	return localStorage.getItem(REFRESH_KEY);
}

export function setRefreshToken(token: string | null): void {
	if (token === null) {
		localStorage.removeItem(REFRESH_KEY);
	} else {
		localStorage.setItem(REFRESH_KEY, token);
	}
}

export function clearAuth(): void {
	accessToken = null;
	setRefreshToken(null);
}

export function venueSlug(): string | null {
	return localStorage.getItem("bookr.venue");
}

export function setVenueSlug(slug: string): void {
	localStorage.setItem("bookr.venue", slug);
}

async function refreshOnce(): Promise<boolean> {
	const refresh = getRefreshToken();
	if (!refresh) return false;
	const response = await fetch("/api/v1/auth/refresh/", {
		method: "POST",
		headers: { "Content-Type": "application/json" },
		body: JSON.stringify({ refresh }),
	});
	if (!response.ok) return false;
	const data = (await response.json()) as { access: string; refresh?: string };
	accessToken = data.access;
	if (data.refresh) setRefreshToken(data.refresh);
	return true;
}

export async function apiFetch(
	path: string,
	init: RequestInit = {},
): Promise<Response> {
	const headers = new Headers(init.headers);
	headers.set("Content-Type", "application/json");
	if (accessToken) headers.set("Authorization", `Bearer ${accessToken}`);
	const venue = venueSlug();
	if (venue) headers.set("X-Venue-Slug", venue);
	let response = await fetch(path, { ...init, headers });
	if (response.status === 401 && (accessToken || getRefreshToken())) {
		const renewed = await refreshOnce();
		if (!renewed) {
			clearAuth();
			window.location.href = "/login";
			return response;
		}
		const retry = new Headers(init.headers);
		retry.set("Content-Type", "application/json");
		if (accessToken) retry.set("Authorization", `Bearer ${accessToken}`);
		if (venue) retry.set("X-Venue-Slug", venue);
		response = await fetch(path, { ...init, headers: retry });
		if (response.status === 401) {
			clearAuth();
			window.location.href = "/login";
		}
	}
	return response;
}

export async function apiJson<T>(
	path: string,
	init: RequestInit = {},
): Promise<T> {
	const response = await apiFetch(path, init);
	if (!response.ok) {
		const error = new Error(`API ${response.status}`) as Error & {
			status: number;
			body: unknown;
		};
		error.status = response.status;
		error.body = await response.json().catch(() => null);
		throw error;
	}
	return (await response.json()) as T;
}
