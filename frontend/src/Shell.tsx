import { useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";
import { Link, Outlet, useNavigate } from "react-router";
import { canTeach, isDeskStaff, useAuth } from "./auth";
import { useVenue } from "./venue";

function VenueSwitcher() {
	const { me } = useAuth();
	const { venue, select } = useVenue();
	const queryClient = useQueryClient();
	const venues = (me?.venues ?? []).map((v) => v.slug);
	const unique = [...new Set(venues)];
	if (unique.length <= 1) return null;
	return (
		<label>
			Venue{" "}
			<select
				data-testid="venue-switcher"
				value={venue ?? ""}
				onChange={(event) => {
					select(event.target.value);
					queryClient.clear();
				}}
			>
				{unique.map((slug) => (
					<option key={slug} value={slug}>
						{slug}
					</option>
				))}
			</select>
		</label>
	);
}

function Shell() {
	const { me, logout } = useAuth();
	const { venue } = useVenue();
	const navigate = useNavigate();
	useEffect(() => {
		if (!localStorage.getItem("bookr.refresh")) navigate("/login");
	}, [navigate]);
	return (
		<div>
			<header>
				<nav>
					<Link to="/">Schedule</Link> <Link to="/calendar">Calendar</Link>{" "}
					<Link to="/bookings">My bookings</Link>{" "}
					<Link to="/passes">Passes</Link> <Link to="/ledger">Ledger</Link>
					{isDeskStaff(me, venue) ? (
						<>
							{" "}
							<Link to="/desk">Desk</Link> {" "}
							<Link to="/manage">Manage</Link>
						</>
					) : null}
					{canTeach(me, venue) ? (
						<>
							{" "}
							<Link to="/teach">Teach</Link>
						</>
					) : null}
				</nav>
				<VenueSwitcher />
				{me ? (
					<span>
						{me.username}{" "}
						<button type="button" onClick={logout}>
							Log out
						</button>
					</span>
				) : null}
			</header>
			<Outlet />
		</div>
	);
}

export default Shell;
export { VenueSwitcher };
