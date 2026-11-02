import { useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";
import { NavLink, Outlet, useNavigate } from "react-router";
import { canBook, canTeach, isDeskStaff, useAuth } from "./auth";
import { useBookings, usePasses } from "./hooks";
import { ErrorBoundary, RouteFocus } from "./route-ux";
import { useVenue, venueTimeZone } from "./venue";

function VenueSwitcher() {
	const { me } = useAuth();
	const { venue, select } = useVenue();
	const queryClient = useQueryClient();
	const venues = (me?.venues ?? []).map((v) => v.slug);
	const unique = [...new Set(venues)];
	const timeZone = venueTimeZone(me, venue);
	return (
		<div className="mt-4 rounded-lg bg-slate-800 px-3 py-2 text-sm">
			<span className="block text-xs uppercase tracking-wider text-slate-400">
				Venue
			</span>
			{unique.length > 1 ? (
				<select
					data-testid="venue-switcher"
					value={venue ?? ""}
					onChange={(event) => {
						select(event.target.value);
						queryClient.clear();
					}}
					className="mt-0.5 w-full bg-transparent font-semibold text-white outline-none"
				>
					{unique.map((slug) => (
						<option key={slug} value={slug} className="text-slate-900">
							{slug}
						</option>
					))}
				</select>
			) : (
				<p className="mt-0.5 font-semibold text-white">{venue}</p>
			)}
			<span className="block text-xs text-slate-400">{timeZone}</span>
		</div>
	);
}

function navClass({ isActive }: { isActive: boolean }): string {
	return `flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium ${
		isActive ? "bg-brand text-white" : "text-slate-300 hover:bg-slate-800"
	}`;
}

function Shell() {
	const { me, logout } = useAuth();
	const { venue } = useVenue();
	const navigate = useNavigate();
	const bookings = useBookings();
	const passes = usePasses();
	useEffect(() => {
		if (!localStorage.getItem("bookr.refresh")) navigate("/login");
	}, [navigate]);
	const activeCount = (bookings.data ?? []).filter((b) =>
		["booked", "waitlisted"].includes(b.status),
	).length;
	const creditsLeft = (passes.data ?? []).reduce(
		(sum, p) => sum + p.credits_remaining,
		0,
	);
	const activePasses = passes.data ?? [];
	return (
		<div className="flex min-h-screen bg-stone-100">
			<aside className="flex w-64 shrink-0 flex-col bg-slate-900 px-4 pb-6 pt-6 text-slate-200">
				<p className="px-1 text-xl font-bold tracking-tight text-white">
					Bookr
				</p>
				<VenueSwitcher />
				<nav className="mt-4 space-y-1">
					<NavLink to="/" end className={navClass}>
						Schedule
					</NavLink>
					<NavLink to="/calendar" className={navClass}>
						Calendar
					</NavLink>
					{canBook(me, venue) ? (
						<>
							<NavLink to="/bookings" className={navClass}>
								<span>My bookings</span>
								{activeCount > 0 ? (
									<span className="ml-auto rounded-full bg-slate-700 px-2 py-0.5 text-xs">
										{activeCount}
									</span>
								) : null}
							</NavLink>
							<NavLink to="/passes" className={navClass}>
								Passes
							</NavLink>
							<NavLink to="/ledger" className={navClass}>
								Ledger
							</NavLink>
						</>
					) : null}
					{isDeskStaff(me, venue) ? (
						<>
							<NavLink to="/desk" className={navClass}>
								Desk
							</NavLink>
							<NavLink to="/manage" className={navClass}>
								Manage
							</NavLink>
						</>
					) : null}
					{canTeach(me, venue) ? (
						<NavLink to="/teach" className={navClass}>
							Teach
						</NavLink>
					) : null}
				</nav>
				<div className="mt-auto space-y-4">
					{canBook(me, venue) && passes.data ? (
						<div className="rounded-lg bg-slate-800 px-3 py-2.5 text-sm">
							<p className="text-xs uppercase tracking-wider text-slate-400">
								Credits left
							</p>
							<p className="text-lg font-bold text-white">
								{activePasses.length === 0 ? (
									<span className="text-sm font-medium text-slate-400">
										No active pass
									</span>
								) : (
									<>
										{creditsLeft}{" "}
										<span className="text-xs font-normal text-slate-400">
											· {activePasses.length} pass
											{activePasses.length === 1 ? "" : "es"} active
										</span>
									</>
								)}
							</p>
						</div>
					) : null}
					{me ? (
						<div className="flex items-center justify-between px-1 text-sm">
							<span className="font-medium">{me.username}</span>
							<button
								type="button"
								onClick={logout}
								className="text-slate-400 hover:text-white"
							>
								Log out
							</button>
						</div>
					) : null}
				</div>
			</aside>
			<div className="min-w-0 flex-1">
				<ErrorBoundary>
					<RouteFocus>
						<Outlet />
					</RouteFocus>
				</ErrorBoundary>
			</div>
		</div>
	);
}

export default Shell;
export { VenueSwitcher };
