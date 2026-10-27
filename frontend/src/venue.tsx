import {
	createContext,
	type ReactNode,
	useCallback,
	useContext,
	useState,
} from "react";
import { setVenueSlug as persistVenue, venueSlug } from "./api/client";

interface VenueState {
	venue: string | null;
	select: (slug: string) => void;
}

const VenueContext = createContext<VenueState | null>(null);

export function VenueProvider({ children }: { children: ReactNode }) {
	const [venue, setVenue] = useState<string | null>(venueSlug());
	const select = useCallback((slug: string) => {
		persistVenue(slug);
		setVenue(slug);
	}, []);
	return (
		<VenueContext.Provider value={{ venue, select }}>
			{children}
		</VenueContext.Provider>
	);
}

export function useVenue(): VenueState {
	const state = useContext(VenueContext);
	if (!state) throw new Error("useVenue needs VenueProvider");
	return state;
}

export function venueTimeZone(
	me: { venues: { slug: string; time_zone: string }[] } | null,
	venue: string | null,
): string {
	return me?.venues.find((info) => info.slug === venue)?.time_zone ?? "UTC";
}

export function formatInVenueTimeZone(iso: string, timeZone: string): string {
	const options: Intl.DateTimeFormatOptions = {
		dateStyle: "medium",
		timeStyle: "short",
	};
	try {
		return new Intl.DateTimeFormat("en-GB", { ...options, timeZone }).format(
			new Date(iso),
		);
	} catch {
		// Unknown zone (see bookr-w1u): show UTC, never blank the page.
		return new Intl.DateTimeFormat("en-GB", { ...options, timeZone: "UTC" }).format(
			new Date(iso),
		);
	}
}
