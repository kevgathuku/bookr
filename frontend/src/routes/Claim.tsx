import { useState } from "react";
import { Link, useSearchParams } from "react-router";
import { Button, ErrorText, Field } from "../components";
import { confirmPasswordReset, requestPasswordReset } from "../hooks";

function apiMessage(failure: unknown, fallback: string): string {
	const body = (failure as { body?: unknown }).body as
		| Record<string, unknown>
		| null
		| undefined;
	if (body && typeof body === "object") {
		if (typeof body.detail === "string") return body.detail;
		const first = Object.values(body).flat()[0];
		if (typeof first === "string") return first;
	}
	return fallback;
}

function Card({ children }: { children: React.ReactNode }) {
	return (
		<main className="mx-auto flex min-h-screen max-w-md flex-col justify-center px-6">
			<div className="rounded-2xl border border-slate-200 bg-white p-8 shadow-sm">
				<p className="text-xl font-bold tracking-tight">Bookr</p>
				{children}
			</div>
		</main>
	);
}

function RequestLink() {
	const [email, setEmail] = useState("");
	const [sent, setSent] = useState<string | null>(null);
	const [error, setError] = useState<string | null>(null);

	async function submit(event: React.SubmitEvent): Promise<void> {
		event.preventDefault();
		setError(null);
		try {
			const result = await requestPasswordReset(email);
			setSent(result.detail);
		} catch {
			setError("Could not send the link. Try again.");
		}
	}

	if (sent)
		return (
			<Card>
				<p data-testid="claim-sent">{sent}</p>
			</Card>
		);

	return (
		<Card>
			<h1 className="mt-1 text-3xl font-bold tracking-tight">
				Set up your account
			</h1>
			<p className="mt-1 text-sm text-slate-500">
				Your studio creates your account first — enter your email and we will
				send you a link to set your password.
			</p>
			<form onSubmit={submit} className="mt-6 space-y-4">
				<Field label="Email" htmlFor="claim-email">
					<input
						data-testid="claim-email"
						id="claim-email"
						className="mt-1 w-full"
						type="email"
						required
						value={email}
						onChange={(event) => setEmail(event.target.value)}
						autoComplete="email"
					/>
				</Field>
				{error ? <ErrorText message={error} /> : null}
				<Button testId="claim-request-button" type="submit" className="w-full">
					Send me the link
				</Button>
			</form>
		</Card>
	);
}

function SetPassword({ uid, token }: { uid: string; token: string }) {
	const [password, setPassword] = useState("");
	const [confirm, setConfirm] = useState("");
	const [done, setDone] = useState(false);
	const [error, setError] = useState<string | null>(null);

	async function submit(event: React.SubmitEvent): Promise<void> {
		event.preventDefault();
		setError(null);
		if (password !== confirm) {
			setError("Passwords do not match.");
			return;
		}
		try {
			await confirmPasswordReset(uid, token, password);
			setDone(true);
		} catch (failure) {
			setError(apiMessage(failure, "This link is invalid or expired."));
		}
	}

	if (done) {
		return (
			<Card>
				<p data-testid="claim-done">
					Password set.{" "}
					<Link
						to="/login"
						className="font-semibold text-brand hover:underline"
					>
						Log in
					</Link>
				</p>
			</Card>
		);
	}

	return (
		<Card>
			<h1 className="mt-1 text-3xl font-bold tracking-tight">
				Choose your password
			</h1>
			<form onSubmit={submit} className="mt-6 space-y-4">
				<Field label="New password" htmlFor="claim-password">
					<input
						data-testid="claim-password"
						id="claim-password"
						className="mt-1 w-full"
						type="password"
						required
						value={password}
						onChange={(event) => setPassword(event.target.value)}
						autoComplete="new-password"
					/>
				</Field>
				<Field label="Confirm password" htmlFor="claim-password-confirm">
					<input
						data-testid="claim-password-confirm"
						id="claim-password-confirm"
						className="mt-1 w-full"
						type="password"
						required
						value={confirm}
						onChange={(event) => setConfirm(event.target.value)}
						autoComplete="new-password"
					/>
				</Field>
				{error ? <ErrorText message={error} /> : null}
				<Button testId="claim-submit-button" type="submit" className="w-full">
					Set password
				</Button>
			</form>
		</Card>
	);
}

export default function Claim() {
	const [params] = useSearchParams();
	const uid = params.get("uid");
	const token = params.get("token");
	if (uid && token) return <SetPassword uid={uid} token={token} />;
	return <RequestLink />;
}
