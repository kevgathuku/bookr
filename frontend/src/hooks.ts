import { useQuery } from "@tanstack/react-query";
import { useMemo } from "react";
import { apiJson } from "./api/client";

export interface ClassItem {
	id: number;
	class_type: number;
	room: number;
	teacher: number;
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

function weekWindow(): { from: string; to: string } {
	const from = new Date();
	const to = new Date(from.getTime() + 7 * 24 * 3600 * 1000);
	return { from: from.toISOString(), to: to.toISOString() };
}

export function useClasses(venue: string | null) {
	const { from, to } = useMemo(() => weekWindow(), []);
	return useQuery({
		queryKey: ["venue", venue, "classes", from, to],
		queryFn: () =>
			apiJson<ClassItem[]>(
				`/api/v1/classes/?from=${encodeURIComponent(from)}&to=${encodeURIComponent(to)}`,
			),
		enabled: venue !== null,
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
