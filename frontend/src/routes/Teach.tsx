import { useAuth } from "../auth";
import { EmptyState, ErrorText } from "../components";
import { useSessions } from "../hooks";
import { SkeletonList } from "../route-ux";
import { formatInVenueTimeZone, useVenue, venueTimeZone } from "../venue";

export default function Teach() {
	const { venue } = useVenue();
	const { me } = useAuth();
	const timeZone = venueTimeZone(me, venue);
	const sessions = useSessions(venue);

	if (sessions.isPending) return <SkeletonList />;
	if (sessions.isError)
		return <ErrorText message="Could not load teaching schedule." />;
	const mine = (sessions.data ?? []).filter(
		(session) => session.teacher === me?.id,
	);
	return (
		<main className="mx-auto max-w-5xl px-6 py-8 lg:px-10">
			<h1 data-testid="teach" className="text-3xl font-bold tracking-tight">
				Teaching schedule
			</h1>
			<p className="mt-1 text-sm text-slate-500">
				Your sessions for the next 7 days.
			</p>
			<section className="mt-8">
				<h2 className="text-lg font-semibold">My sessions</h2>
				<div className="mt-3">
					{mine.length === 0 ? (
						<EmptyState message="No sessions assigned this week." />
					) : (
						<ul className="space-y-3">
							{mine.map((session) => (
								<li
									key={session.id}
									data-testid="teach-class-row"
									className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm"
								>
									<p className="font-semibold">{session.offering_title}</p>
									<p className="mt-0.5 text-sm text-slate-500">
										{formatInVenueTimeZone(session.starts_at, timeZone)}
									</p>
								</li>
							))}
						</ul>
					)}
				</div>
			</section>
		</main>
	);
}
