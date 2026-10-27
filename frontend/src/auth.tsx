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

export interface Membership {
	organization: string;
	venue: string | null;
	role: string;
}

export interface VenueInfo {
	organization: string;
	slug: string;
	name: string;
}

export interface Me {
	username: string;
	memberships: Membership[];
	venues: VenueInfo[];
}

interface AuthState {
	me: Me | null;
	login: (username: string, password: string) => Promise<void>;
	logout: () => void;
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
	const [me, setMe] = useState<Me | null>(null);
	const queryClient = useQueryClient();

	useEffect(() => {
		if (!localStorage.getItem("bookr.refresh")) return;
		apiJson<Me>("/api/v1/me/")
			.then((profile) => setMe(profile))
			.catch(() => clearAuth());
	}, []);

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
				localStorage.setItem("bookr.venue", profile.venues[0].slug);
			}
			queryClient.clear();
		},
		[queryClient],
	);

	const logout = useCallback(() => {
		clearAuth();
		setMe(null);
		queryClient.clear();
	}, [queryClient]);

	return (
		<AuthContext.Provider value={{ me, login, logout }}>
			{children}
		</AuthContext.Provider>
	);
}

export function useAuth(): AuthState {
	const auth = useContext(AuthContext);
	if (!auth) throw new Error("useAuth needs AuthProvider");
	return auth;
}
