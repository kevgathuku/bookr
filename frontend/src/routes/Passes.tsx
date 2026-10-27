import { useAuth } from "../auth";
import { EmptyState, ErrorText } from "../components";
import { SkeletonList } from "../route-ux";
import { usePasses } from "../hooks";
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
		<main>
			<h1 data-testid="passes">My passes</h1>
			<ul>
				{passes.data.map((pass) => (
					<li key={pass.id} data-testid="pass-row">
						<span>{pass.product_name}</span>{" "}
						<span>
							{pass.credits_total - pass.credits_used}/{pass.credits_total}{" "}
							credits left
						</span>{" "}
						<span>
							expires{" "}
							{pass.valid_until
								? formatInVenueTimeZone(pass.valid_until, timeZone)
								: "never"}
						</span>{" "}
						<span>{pass.status}</span>
					</li>
				))}
			</ul>
		</main>
	);
}
