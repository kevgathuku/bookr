import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Navigate, Outlet, Route, Routes } from "react-router";
import { AuthProvider, isDeskStaff, useAuth } from "./auth";
import { NotFound } from "./route-ux";
import Bookings from "./routes/Bookings";
import Calendar from "./routes/Calendar";
import Desk from "./routes/Desk";
import Ledger from "./routes/Ledger";
import Login from "./routes/Login";
import Manage from "./routes/Manage";
import Passes from "./routes/Passes";
import Schedule from "./routes/Schedule";
import Teach from "./routes/Teach";
import Shell from "./Shell";
import { useVenue, VenueProvider } from "./venue";

const queryClient = new QueryClient();

function ScheduleRoute() {
	const { venue } = useVenue();
	return <Schedule venue={venue} />;
}

function RequireVenue() {
	const { me, recovered } = useAuth();
	if (!recovered) return <p>Loading…</p>;
	if (!me) return <Navigate to="/login" />;
	return <ScheduleRoute />;
}

function RequireStaff() {
	const { me } = useAuth();
	const { venue } = useVenue();
	if (!me) return <Navigate to="/login" />;
	if (!isDeskStaff(me, venue)) return <Navigate to="/" />;
	return <Outlet />;
}

export default function App() {
	return (
		<QueryClientProvider client={queryClient}>
			<VenueProvider>
				<AuthProvider>
					<BrowserRouter>
						<Routes>
							<Route path="/login" element={<Login />} />
							<Route element={<Shell />}>
								<Route path="/" element={<RequireVenue />} />
								<Route path="/bookings" element={<Bookings />} />
								<Route path="/calendar" element={<Calendar />} />
								<Route path="/passes" element={<Passes />} />
								<Route path="/ledger" element={<Ledger />} />
								<Route path="/teach" element={<Teach />} />
								<Route element={<RequireStaff />}>
									<Route path="/desk" element={<Desk />} />
									<Route path="/manage" element={<Manage />} />
								</Route>
								<Route path="*" element={<NotFound />} />
							</Route>
						</Routes>
					</BrowserRouter>
				</AuthProvider>
			</VenueProvider>
		</QueryClientProvider>
	);
}
