import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Button, EmptyState, ErrorText } from "../components";
import { bookClass, type ClassItem, useBookings, useClasses } from "../hooks";

function formatTime(iso: string): string {
	return new Date(iso).toLocaleString([], {
		weekday: "short",
		hour: "2-digit",
		minute: "2-digit",
	});
}

function ClassRow({ klass, booked }: { klass: ClassItem; booked: boolean }) {
	const queryClient = useQueryClient();
	const [error, setError] = useState<string | null>(null);
	const booking = useMutation({
		mutationFn: (waitlist: boolean) =>
			bookClass(klass.id, crypto.randomUUID(), waitlist),
		onSuccess: () => {
			setError(null);
			void queryClient.invalidateQueries();
		},
		onError: (failure: unknown) => {
			const status = (failure as { status?: number }).status;
			if (status === 409) {
				setError("Class is full.");
			} else if (status === 402) {
				setError("No credits left on your passes.");
			} else {
				setError("Booking failed. Try again.");
			}
		},
	});

	return (
		<li data-testid="class-row">
			<span>
				{formatTime(klass.starts_at)} — {klass.status}
			</span>
			{booked ? (
				<span data-testid="booked-badge">Booked</span>
			) : (
				<>
					<Button
						testId={`book-button-${klass.id}`}
						disabled={booking.isPending}
						onClick={() => booking.mutate(false)}
					>
						Book
					</Button>
					{error === "Class is full." ? (
						<Button
							testId={`waitlist-button-${klass.id}`}
							disabled={booking.isPending}
							onClick={() => booking.mutate(true)}
						>
							Join waitlist
						</Button>
					) : null}
				</>
			)}
			{error ? <ErrorText message={error} /> : null}
		</li>
	);
}

export default function Schedule({ venue }: { venue: string | null }) {
	const classes = useClasses(venue);
	const bookings = useBookings();

	if (classes.isPending || bookings.isPending) return <p>Loading schedule…</p>;
	if (classes.isError) return <ErrorText message="Could not load classes." />;
	const bookedIds = new Set(
		(bookings.data ?? [])
			.filter((b) => b.status === "confirmed" || b.status === "waitlisted")
			.map((b) => b.scheduled_class),
	);
	if (classes.data.length === 0)
		return <EmptyState message="No classes this week." />;
	return (
		<main>
			<h1 data-testid="schedule">Schedule</h1>
			<ul>
				{classes.data.map((klass) => (
					<ClassRow
						key={klass.id}
						klass={klass}
						booked={bookedIds.has(klass.id)}
					/>
				))}
			</ul>
		</main>
	);
}
