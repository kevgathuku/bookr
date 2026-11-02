import { useState } from "react";
import { Link, useNavigate } from "react-router";
import { useAuth } from "../auth";
import { Button, ErrorText, Field } from "../components";

export default function Login() {
	const { login } = useAuth();
	const navigate = useNavigate();
	const [username, setUsername] = useState("");
	const [password, setPassword] = useState("");
	const [error, setError] = useState<string | null>(null);

	async function submit(event: React.FormEvent): Promise<void> {
		event.preventDefault();
		setError(null);
		try {
			await login(username, password);
			navigate("/");
		} catch {
			setError("Login failed — check your username and password.");
		}
	}

	return (
		<main className="mx-auto flex min-h-screen max-w-md flex-col justify-center px-6">
			<div className="rounded-2xl border border-slate-200 bg-white p-8 shadow-sm">
				<p className="text-xl font-bold tracking-tight">Bookr</p>
				<h1 className="mt-1 text-3xl font-bold tracking-tight">
					Log in to Bookr
				</h1>
				<form onSubmit={submit} className="mt-6 space-y-4">
					<Field label="Username" htmlFor="username">
						<input
							data-testid="username"
							id="username"
							className="mt-1 w-full"
							value={username}
							onChange={(event) => setUsername(event.target.value)}
							autoComplete="username"
						/>
					</Field>
					<Field label="Password" htmlFor="password">
						<input
							data-testid="password"
							id="password"
							className="mt-1 w-full"
							type="password"
							value={password}
							onChange={(change) => setPassword(change.target.value)}
							autoComplete="current-password"
						/>
					</Field>
					{error ? <ErrorText message={error} /> : null}
					<Button testId="login-button" type="submit" className="w-full">
						Log in
					</Button>
					<p className="text-center text-sm">
						<Link
							to="/claim"
							className="font-semibold text-brand hover:underline"
						>
							New here, or forgot your password?
						</Link>
					</p>
				</form>
			</div>
		</main>
	);
}
