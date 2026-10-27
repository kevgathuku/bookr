import { useQuery } from "@tanstack/react-query";
import { useMemo } from "react";
import { apiJson } from "./api/client";

export interface ClassItem {
	id: number;
	class_type: number;
	class_type_name: string;
	room: number;
	room_name: string;
	teacher: number;
	teacher_name: string;
	starts_at: string;
	ends_at: string;
	status: string;
	capacity: number | null;
}

export interface BookingItem {
	id: number;
	status: string;
	scheduled_class: number | null;
	hold_until: string | null;
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

export function useClasses(
	venue: string | null,
	range: { from: string; to: string } | null = null,
) {
	const window = useMemo(() => range ?? weekWindow(), [range]);
	const { from, to } = window;
	return useQuery({
		queryKey: ["venue", venue, "classes", from, to],
		queryFn: () =>
			apiJson<ClassItem[]>(
				`/api/v1/classes/?from=${encodeURIComponent(from)}&to=${encodeURIComponent(to)}`,
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

export interface MemberPassItem {
	id: number;
	product: number;
	product_name: string;
	credits_total: number;
	credits_used: number;
	valid_from: string;
	valid_until: string | null;
	status: string;
}

export interface LedgerEntryItem {
	id: number;
	member_pass: number;
	booking: number | null;
	delta: number;
	reason: string;
	created_by: number | null;
	created_at: string;
}

export function useCalendarEvents(
	venue: string | null,
	range: { from: string; to: string },
	teacher: number | null,
	room: number | null,
) {
	const params = new URLSearchParams({
		from: range.from,
		to: range.to,
	});
	if (teacher !== null) params.set("teacher", String(teacher));
	if (room !== null) params.set("room", String(room));
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
		queryFn: () => apiJson<MemberPassItem[]>("/api/v1/me/passes/"),
	});
}

export function useLedger() {
	return useQuery({
		queryKey: ["ledger", "mine"],
		queryFn: () => apiJson<LedgerEntryItem[]>("/api/v1/ledger/"),
	});
}

export function useBookings() {
	return useQuery({
		queryKey: ["bookings", "mine"],
		queryFn: () => apiJson<BookingItem[]>("/api/v1/bookings/?mine=true"),
	});
}

export async function bookClass(
	classId: number,
	idempotencyKey: string,
	waitlist = false,
): Promise<BookingItem> {
	const query = waitlist ? "?waitlist=true" : "";
	return apiJson<BookingItem>(`/api/v1/bookings/${query}`, {
		method: "POST",
		body: JSON.stringify({
			scheduled_class: classId,
			idempotency_key: idempotencyKey,
		}),
	});
}
