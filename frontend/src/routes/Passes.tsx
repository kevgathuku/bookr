import { useAuth } from "../auth";
import { EmptyState, ErrorText, Pill } from "../components";
import { usePasses } from "../hooks";
import { SkeletonList } from "../route-ux";
import { formatInVenueTimeZone, useVenue, venueTimeZone } from "../venue";

export default function Passes() {
	const { venue } = useVenue();
	const { me } = useAuth();
	const timeZone = venueTimeZone(me, venue);
	const passes = usePasses();

	if (passes.isPending) return <SkeletonList />;
	if (passes.isError) return <ErrorText message="Could not load passes." />;
	if (passes.data.length === 0)
		return <EmptyState message="No passes yet. Buy one at the front desk." />;
	return (
		<main className="mx-auto max-w-5xl px-6 py-8 lg:px-10">
			<h1 data-testid="passes" className="text-3xl font-bold tracking-tight">
				My passes
			</h1>
			<p className="mt-1 text-sm text-slate-500">
				Each class spends one credit; unlimited passes spend nothing.
			</p>
			<ul className="mt-5 space-y-3">
				{passes.data.map((pass) => {
					const left = pass.credits_remaining;
					return (
						<li
							key={pass.id}
							data-testid="pass-row"
							className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm"
						>
							<p className="font-semibold">
								{pass.plan_name} <Pill tone="ok">{pass.plan_type}</Pill>
							</p>
							<p className="mt-0.5 text-sm text-slate-500">
								{left} credits left · expires{" "}
								{formatInVenueTimeZone(pass.ends_on, timeZone)}
							</p>
						</li>
					);
				})}
			</ul>
		</main>
	);
}
