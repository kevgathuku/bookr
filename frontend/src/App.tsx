import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Navigate, Route, Routes } from "react-router";
import { venueSlug } from "./api/client";
import { AuthProvider, useAuth } from "./auth";
import Bookings from "./routes/Bookings";
import Login from "./routes/Login";
import Schedule from "./routes/Schedule";
import Shell from "./Shell";

const queryClient = new QueryClient();

function ScheduleRoute() {
	return <Schedule venue={venueSlug()} />;
}

function RequireVenue() {
	const { me } = useAuth();
	if (!me) return <p>Loading…</p>;
	return <ScheduleRoute />;
}

export default function App() {
	return (
		<QueryClientProvider client={queryClient}>
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
		</QueryClientProvider>
	);
}
