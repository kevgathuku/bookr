import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Link, Outlet, useNavigate } from "react-router";
import { setVenueSlug, venueSlug } from "./api/client";
import { useAuth } from "./auth";

function VenueSwitcher() {
	const { me } = useAuth();
	const queryClient = useQueryClient();
	const venues = (me?.venues ?? []).map((v) => v.slug);
	const unique = [...new Set(venues)];
	const [current, setCurrent] = useState<string | null>(venueSlug());
	if (unique.length <= 1) return null;
	return (
		<label>
			Venue{" "}
			<select
				data-testid="venue-switcher"
				value={current ?? ""}
				onChange={(event) => {
					setVenueSlug(event.target.value);
					setCurrent(event.target.value);
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
	const navigate = useNavigate();
	useEffect(() => {
		if (!localStorage.getItem("bookr.refresh")) navigate("/login");
	}, [navigate]);
	return (
		<div>
			<header>
				<nav>
					<Link to="/">Schedule</Link> <Link to="/bookings">My bookings</Link>
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
