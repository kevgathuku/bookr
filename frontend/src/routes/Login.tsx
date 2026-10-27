import { useState } from "react";
import { useNavigate } from "react-router";
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
		<main>
			<h1>Log in to Bookr</h1>
			<form onSubmit={submit}>
				<Field label="Username" htmlFor="username">
					<input
						data-testid="username"
						id="username"
						value={username}
						onChange={(event) => setUsername(event.target.value)}
						autoComplete="username"
					/>
				</Field>
				<Field label="Password" htmlFor="password">
					<input
						data-testid="password"
						id="password"
						type="password"
						value={password}
						onChange={(event) => setPassword(event.target.value)}
						autoComplete="current-password"
					/>
				</Field>
				{error ? <ErrorText message={error} /> : null}
				<Button testId="login-button" type="submit">
					Log in
				</Button>
			</form>
		</main>
	);
}
