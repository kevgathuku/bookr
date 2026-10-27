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
