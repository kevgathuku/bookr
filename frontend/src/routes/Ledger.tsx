import { useAuth } from "../auth";
import { EmptyState, ErrorText } from "../components";
import { useLedger } from "../hooks";
import { formatInVenueTimeZone, useVenue, venueTimeZone } from "../venue";

export default function Ledger() {
	const { venue } = useVenue();
	const { me } = useAuth();
	const timeZone = venueTimeZone(me, venue);
	const ledger = useLedger();

	if (ledger.isPending) return <p>Loading ledger…</p>;
	if (ledger.isError) return <ErrorText message="Could not load ledger." />;
	if (ledger.data.length === 0)
		return <EmptyState message="No credit movements yet." />;
	return (
		<main>
			<h1 data-testid="ledger">Credit history</h1>
			<ul>
				{ledger.data.map((entry) => (
					<li key={entry.id} data-testid="ledger-row">
						<span>{formatInVenueTimeZone(entry.created_at, timeZone)}</span>{" "}
						<span>
							{entry.delta > 0 ? "+" : ""}
							{entry.delta}
						</span>{" "}
						<span>{entry.reason}</span>
						{entry.note ? <span> — {entry.note}</span> : null}
					</li>
				))}
			</ul>
		</main>
	);
}
