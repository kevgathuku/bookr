import { useAuth } from "../auth";
import { EmptyState, ErrorText } from "../components";
import { useLedger } from "../hooks";
import { SkeletonList } from "../route-ux";
import { formatInVenueTimeZone, useVenue, venueTimeZone } from "../venue";

export default function Ledger() {
	const { venue } = useVenue();
	const { me } = useAuth();
	const timeZone = venueTimeZone(me, venue);
	const ledger = useLedger();

	if (ledger.isPending) return <SkeletonList />;
	if (ledger.isError) return <ErrorText message="Could not load ledger." />;
	if (ledger.data.length === 0)
		return <EmptyState message="No credit movements yet." />;
	return (
		<main className="mx-auto max-w-5xl px-6 py-8 lg:px-10">
			<h1 data-testid="ledger" className="text-3xl font-bold tracking-tight">
				Credit history
			</h1>
			<p className="mt-1 text-sm text-slate-500">
				Append-only: every purchase, booking, refund, and adjustment.
			</p>
			<ul className="mt-5 space-y-3">
				{ledger.data.map((entry) => (
					<li
						key={entry.id}
						data-testid="ledger-row"
						className="flex items-baseline gap-4 rounded-2xl border border-slate-200 bg-white p-4 shadow-sm"
					>
						<span
							className={`w-12 shrink-0 text-lg font-bold tabular-nums ${
								entry.delta > 0 ? "text-ok" : "text-bad"
							}`}
						>
							{entry.delta > 0 ? "+" : ""}
							{entry.delta}
						</span>
						<div className="min-w-0 flex-1">
							<p className="font-semibold">{entry.reason}</p>
							{entry.note ? (
								<p className="mt-0.5 text-sm text-slate-500">— {entry.note}</p>
							) : null}
						</div>
						<span className="shrink-0 text-sm text-slate-500">
							{formatInVenueTimeZone(entry.created_at, timeZone)}
						</span>
					</li>
				))}
			</ul>
		</main>
	);
}
