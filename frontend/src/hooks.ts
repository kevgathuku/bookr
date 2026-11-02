import { useQuery } from "@tanstack/react-query";
import { useMemo } from "react";
import { apiJson } from "./api/client";

export interface SessionItem {
	id: number;
	venue: number;
	offering: number;
	offering_title: string;
	category: string;
	teacher: number;
	teacher_name: string;
	starts_at: string;
	ends_at: string;
	capacity: number | null;
	spots_left: number | null;
}

export interface BookingItem {
	id: number;
	session: number;
	session_title: string;
	status: string;
	created_at: string;
}

export type BookError = "full" | "no-credits" | "failed";

export function bookErrorOf(failure: unknown): BookError {
	const status = (failure as { status?: number }).status;
	if (status === 409) return "full";
	if (status === 402) return "no-credits";
	return "failed";
}

export const BOOK_ERROR_MESSAGE: Record<BookError, string> = {
	full: "Class is full.",
	"no-credits": "No credits left on your passes.",
	failed: "Booking failed. Try again.",
};

function weekWindow(): { from: string; to: string } {
	const from = new Date();
	const to = new Date(from.getTime() + 7 * 24 * 3600 * 1000);
	return { from: from.toISOString(), to: to.toISOString() };
}

export function useSessions(
	venue: string | null,
	range: { from: string; to: string } | null = null,
) {
	const window = useMemo(() => range ?? weekWindow(), [range]);
	const { from, to } = window;
	return useQuery({
		queryKey: ["venue", venue, "sessions", from, to],
		queryFn: () =>
			apiJson<SessionItem[]>(
				`/api/v1/sessions/?from=${encodeURIComponent(from)}&to=${encodeURIComponent(to)}`,
			),
		enabled: venue !== null,
	});
}

export interface CalendarEventItem {
	kind: string;
	id: number;
	title: string;
	starts_at: string;
	ends_at: string;
	room: string | null;
	teacher: number;
}

export interface MembershipItem {
	id: number;
	plan: number;
	plan_name: string;
	plan_type: string;
	credits_remaining: number;
	starts_on: string;
	ends_on: string;
}

export interface LedgerEntryItem {
	id: number;
	membership: number;
	booking: number | null;
	delta: number;
	reason: string;
	note: string;
	created_by: number | null;
	created_at: string;
}

export function useCalendarEvents(
	venue: string | null,
	range: { from: string; to: string },
	teacher: number | null,
) {
	const params = new URLSearchParams({
		from: range.from,
		to: range.to,
	});
	if (teacher !== null) params.set("teacher", String(teacher));
	const query = params.toString();
	return useQuery({
		queryKey: ["venue", venue, "calendar", query],
		queryFn: () => apiJson<CalendarEventItem[]>(`/api/v1/calendar/?${query}`),
		enabled: venue !== null,
	});
}

export function usePasses() {
	return useQuery({
		queryKey: ["passes", "mine"],
		queryFn: () => apiJson<MembershipItem[]>("/api/v1/memberships/"),
	});
}

export function useLedger() {
	return useQuery({
		queryKey: ["ledger", "mine"],
		queryFn: () => apiJson<LedgerEntryItem[]>("/api/v1/ledger/"),
	});
}

export interface RosterRow {
	id: number;
	member: string;
	class_title: string;
	starts_at: string;
	status: string;
	checked_in_at: string | null;
}

export function useRoster(date: string | null) {
	const params = date ? `?date=${encodeURIComponent(date)}` : "";
	return useQuery({
		queryKey: ["desk", "roster", date ?? "today"],
		queryFn: () => apiJson<RosterRow[]>(`/api/v1/bookings/roster/${params}`),
	});
}

export interface MemberHit {
	id: number;
	username: string;
}

export async function searchMembers(query: string): Promise<MemberHit[]> {
	return apiJson<MemberHit[]>(
		`/api/v1/members/search/?q=${encodeURIComponent(query)}`,
	);
}

export function useMemberPasses(memberId: number | null) {
	return useQuery({
		queryKey: ["desk", "passes", memberId],
		queryFn: () =>
			apiJson<MembershipItem[]>(`/api/v1/memberships/?member=${memberId}`),
		enabled: memberId !== null,
	});
}

export interface DoorEvent {
	id: number;
	access_point: number;
	member: number | null;
	granted: boolean;
	reason: string;
}

export function useDoorEvents() {
	return useQuery({
		queryKey: ["desk", "door-events"],
		queryFn: () => apiJson<DoorEvent[]>("/api/v1/access/events/"),
		refetchInterval: 15000,
	});
}

export async function checkinBooking(bookingId: number): Promise<void> {
	await apiJson(`/api/v1/bookings/${bookingId}/checkin/`, { method: "POST" });
}

export async function noShowBooking(bookingId: number): Promise<void> {
	await apiJson(`/api/v1/bookings/${bookingId}/no-show/`, { method: "POST" });
}

export async function cancelBookingOverride(
	bookingId: number,
	reason: string,
): Promise<void> {
	await apiJson(`/api/v1/bookings/${bookingId}/cancel/`, {
		method: "POST",
		body: JSON.stringify({ staff_override: true, reason }),
	});
}

export async function adjustPass(
	passId: number,
	delta: number,
	reason: string,
): Promise<void> {
	await apiJson("/api/v1/ledger/adjust/", {
		method: "POST",
		body: JSON.stringify({ membership: passId, delta, reason }),
	});
}

export interface StaffAggregatorItem {
	slug: string;
	name: string;
	seat_allotment: number;
	cancel_cutoff_minutes: number;
	commission_percent: string;
	active: boolean;
	webhook_url: string;
}

export function useStaffAggregators() {
	return useQuery({
		queryKey: ["manage", "aggregators"],
		queryFn: () => apiJson<StaffAggregatorItem[]>("/api/v1/staff/aggregators/"),
	});
}

export async function createStaffAggregator(body: {
	slug: string;
	name: string;
	seat_allotment: number;
}): Promise<{ api_token: string }> {
	return apiJson<{ api_token: string }>("/api/v1/staff/aggregators/", {
		method: "POST",
		body: JSON.stringify(body),
	});
}

export async function rotateStaffAggregator(
	slug: string,
): Promise<{ api_token: string }> {
	return apiJson<{ api_token: string }>(
		`/api/v1/staff/aggregators/${slug}/rotate/`,
		{
			method: "POST",
		},
	);
}

export interface AggEventItem {
	id: number;
	method: string;
	path: string;
	status_code: number;
	created_at: string;
}

export function useAggEvents(slug: string | null) {
	return useQuery({
		queryKey: ["manage", "agg-events", slug],
		queryFn: () =>
			apiJson<AggEventItem[]>(`/api/v1/staff/aggregators/${slug}/events/`),
		enabled: slug !== null,
	});
}

export function useBookings() {
	return useQuery({
		queryKey: ["bookings", "mine"],
		queryFn: () => apiJson<BookingItem[]>("/api/v1/bookings/?mine=true"),
	});
}

export async function bookSession(
	sessionId: number,
	waitlist = false,
): Promise<BookingItem> {
	const query = waitlist ? "?waitlist=true" : "";
	return apiJson<BookingItem>(`/api/v1/bookings/${query}`, {
		method: "POST",
		body: JSON.stringify({ session: sessionId }),
	});
}
