import { useMutation, useQueryClient } from "@tanstack/react-query";
import { apiJson } from "../api/client";
import { useAuth } from "../auth";
import { Button, EmptyState, ErrorText, Pill } from "../components";
import { useBookings } from "../hooks";
import { SkeletonList } from "../route-ux";
import { useVenue, venueTimeZone } from "../venue";

export default function Bookings() {
	const bookings = useBookings();
	const { venue } = useVenue();
	const { me } = useAuth();
	const timeZone = venueTimeZone(me, venue);
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
		<main className="mx-auto max-w-5xl px-6 py-8 lg:px-10">
			<h1 className="text-3xl font-bold tracking-tight">My bookings</h1>
			<p className="mt-1 text-sm text-slate-500">
				Cancelling inside the window refunds the credit; late cancels forfeit
				it.
			</p>
			<ul className="mt-5 space-y-3">
				{active.map((booking) => (
					<li
						key={booking.id}
						data-testid="booking-row"
						className="flex items-center gap-5 rounded-2xl border border-slate-200 bg-white p-4 shadow-sm"
					>
						<div className="min-w-0 flex-1">
							<p className="font-semibold">
								Class {booking.scheduled_class}{" "}
								{booking.status === "waitlisted" ? (
									<Pill tone="warn">Waitlisted</Pill>
								) : (
									<Pill tone="brand">Confirmed</Pill>
								)}
							</p>
							<p className="mt-0.5 text-sm text-slate-500">
								{booking.hold_until
									? `Hold expires ${new Intl.DateTimeFormat("en-GB", {
											timeZone,
											dateStyle: "medium",
											timeStyle: "short",
										}).format(new Date(booking.hold_until))}`
									: "Seat held"}
							</p>
						</div>
						<Button
							testId="cancel-button"
							variant="outline"
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
