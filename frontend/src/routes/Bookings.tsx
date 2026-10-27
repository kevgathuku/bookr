import { useMutation, useQueryClient } from "@tanstack/react-query";
import { apiJson } from "../api/client";
import { Button, EmptyState, ErrorText } from "../components";
import { SkeletonList } from "../route-ux";
import { useBookings } from "../hooks";

export default function Bookings() {
	const bookings = useBookings();
	const queryClient = useQueryClient();
	const cancel = useMutation({
		mutationFn: (id: number) =>
			apiJson(`/api/v1/bookings/${id}/cancel/`, { method: "POST" }),
		onSuccess: () => queryClient.invalidateQueries(),
	});

	if (bookings.isPending) return <SkeletonList />;
	if (bookings.isError) return <ErrorText message="Could not load bookings." />;
	const active = bookings.data.filter((b) =>
		["confirmed", "waitlisted"].includes(b.status),
	);
	if (active.length === 0)
		return <EmptyState message="No bookings yet — pick a class above." />;
	return (
		<main>
			<h1>My bookings</h1>
			<ul>
				{active.map((booking) => (
					<li key={booking.id} data-testid="booking-row">
						<span>
							Class {booking.scheduled_class} — {booking.status}
						</span>
						<Button
							testId="cancel-button"
							disabled={cancel.isPending}
							onClick={() => cancel.mutate(booking.id)}
						>
							Cancel
						</Button>
					</li>
				))}
			</ul>
			{cancel.isError ? <ErrorText message="Cancel failed." /> : null}
		</main>
	);
}
