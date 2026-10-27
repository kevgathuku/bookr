import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Navigate, Route, Routes } from "react-router";
import { AuthProvider, useAuth } from "./auth";
import Bookings from "./routes/Bookings";
import Login from "./routes/Login";
import Schedule from "./routes/Schedule";
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
								<Route path="*" element={<Navigate to="/" />} />
							</Route>
						</Routes>
					</BrowserRouter>
				</AuthProvider>
			</VenueProvider>
		</QueryClientProvider>
	);
}
