import { useQueryClient } from "@tanstack/react-query";
import {
	createContext,
	type ReactNode,
	useCallback,
	useContext,
	useEffect,
	useState,
} from "react";
import {
	apiJson,
	clearAuth,
	setAccessToken,
	setRefreshToken,
} from "./api/client";
import { useVenue } from "./venue";

export interface Membership {
	organization: string;
	venue: string | null;
	role: string;
}

export interface VenueInfo {
	organization: string;
	slug: string;
	name: string;
	time_zone: string;
}

export interface Me {
	id: number;
	username: string;
	memberships: Membership[];
	venues: VenueInfo[];
}

const DESK_ROLES = new Set(["owner", "manager", "frontdesk"]);

export function canTeach(me: Me | null, venue: string | null): boolean {
	return (
		me?.memberships.some(
			(membership) =>
				membership.role !== "member" &&
				(membership.venue === venue || membership.venue === null),
		) ?? false
	);
}

export function isDeskStaff(me: Me | null, venue: string | null): boolean {
	return (
		me?.memberships.some(
			(membership) =>
				DESK_ROLES.has(membership.role) &&
				(membership.venue === venue || membership.venue === null),
		) ?? false
	);
}

interface AuthState {
	me: Me | null;
	recovered: boolean;
	login: (username: string, password: string) => Promise<void>;
	logout: () => void;
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
	const [me, setMe] = useState<Me | null>(null);
	const [recovered, setRecovered] = useState(false);
	const queryClient = useQueryClient();

	const { select } = useVenue();

	useEffect(() => {
		if (!localStorage.getItem("bookr.refresh")) {
			setRecovered(true);
			return;
		}
		apiJson<Me>("/api/v1/me/")
			.then((profile) => {
				setMe(profile);
				if (profile.venues.length > 0) select(profile.venues[0].slug);
			})
			.catch(() => clearAuth())
			.finally(() => setRecovered(true));
	}, [select]);

	const login = useCallback(
		async (username: string, password: string) => {
			const tokens = await apiJson<{ access: string; refresh: string }>(
				"/api/v1/auth/token/",
				{ method: "POST", body: JSON.stringify({ username, password }) },
			);
			setAccessToken(tokens.access);
			setRefreshToken(tokens.refresh);
			const profile = await apiJson<Me>("/api/v1/me/");
			setMe(profile);
			if (profile.venues.length > 0) {
				select(profile.venues[0].slug);
			}
			queryClient.clear();
		},
		[queryClient, select],
	);

	const logout = useCallback(() => {
		clearAuth();
		setMe(null);
		queryClient.clear();
		window.location.href = "/login";
	}, [queryClient]);

	return (
		<AuthContext.Provider value={{ me, recovered, login, logout }}>
			{children}
		</AuthContext.Provider>
	);
}

export function useAuth(): AuthState {
	const auth = useContext(AuthContext);
	if (!auth) throw new Error("useAuth needs AuthProvider");
	return auth;
}
