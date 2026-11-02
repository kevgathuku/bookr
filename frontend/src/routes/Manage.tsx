import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Button, EmptyState, ErrorText } from "../components";
import {
	createStaffAggregator,
	rotateStaffAggregator,
	useAggEvents,
	useStaffAggregators,
} from "../hooks";
import { MemberLookup } from "./Desk";

function useRefresh(keys: string[]) {
	const queryClient = useQueryClient();
	const [error, setError] = useState<string | null>(null);
	return {
		error,
		refresh: () => {
			setError(null);
			void queryClient.invalidateQueries({ queryKey: keys });
		},
		fail: () => setError("Action failed. Try again."),
	};
}

function AggregatorSection() {
	const partners = useStaffAggregators();
	const tools = useRefresh(["manage", "aggregators"]);
	const [slug, setSlug] = useState("");
	const [name, setName] = useState("");
	const [token, setToken] = useState<string | null>(null);
	const [eventsSlug, setEventsSlug] = useState<string | null>(null);
	const events = useAggEvents(eventsSlug);
	const create = useMutation({
		mutationFn: () => createStaffAggregator({ slug, name, seat_allotment: 4 }),
		onSuccess: (data) => {
			setToken(data.api_token);
			tools.refresh();
		},
		onError: tools.fail,
	});
	const rotate = useMutation({
		mutationFn: (partnerSlug: string) => rotateStaffAggregator(partnerSlug),
		onSuccess: (data) => {
			setToken(data.api_token);
			tools.refresh();
		},
		onError: tools.fail,
	});

	return (
		<section className="mt-8">
			<h2 className="text-lg font-semibold">Aggregators</h2>
			<form
				className="mt-3 flex flex-wrap items-center gap-2"
				onSubmit={(event) => {
					event.preventDefault();
					create.mutate();
				}}
			>
				<input
					data-testid="agg-form-slug"
					placeholder="Slug"
					value={slug}
					onChange={(change) => setSlug(change.target.value)}
				/>{" "}
				<input
					data-testid="agg-form-name"
					placeholder="Name"
					value={name}
					onChange={(change) => setName(change.target.value)}
				/>{" "}
				<Button
					testId="agg-create-button"
					type="submit"
					disabled={create.isPending}
				>
					Create partner
				</Button>
			</form>
			{token ? (
				<p data-testid="agg-token">Token (shown once): {token}</p>
			) : null}
			<ul className="mt-3 space-y-3">
				{(partners.data ?? []).map((partner) => (
					<li
						key={partner.slug}
						data-testid="agg-row"
						className="flex flex-wrap items-center gap-2 rounded-2xl border border-slate-200 bg-white p-4 shadow-sm"
					>
						{partner.slug} (allotment {partner.seat_allotment}){" "}
						<Button
							testId={`agg-rotate-${partner.slug}`}
							disabled={rotate.isPending}
							onClick={() => rotate.mutate(partner.slug)}
						>
							Rotate token
						</Button>{" "}
						<Button
							testId={`agg-events-${partner.slug}`}
							onClick={() => setEventsSlug(partner.slug)}
						>
							Log
						</Button>
					</li>
				))}
			</ul>
			{eventsSlug ? (
				(events.data ?? []).length === 0 ? (
					<EmptyState message="No calls logged for this partner yet." />
				) : (
					<ul className="mt-3 space-y-3">
						{(events.data ?? []).map((event) => (
							<li
								key={event.id}
								data-testid="agg-event-row"
								className="rounded-2xl border border-slate-200 bg-white p-4 font-mono text-sm shadow-sm"
							>
								{event.method} {event.path} → {event.status_code}
							</li>
						))}
					</ul>
				)
			) : null}
			{tools.error ? <ErrorText message={tools.error} /> : null}
		</section>
	);
}

export default function Manage() {
	return (
		<main className="mx-auto max-w-5xl px-6 py-8 lg:px-10">
			<h1 data-testid="manage" className="text-3xl font-bold tracking-tight">
				Manage
			</h1>
			<p className="mt-1 text-sm text-slate-500">
				Partner aggregators. Classes, plans, and policies live in the admin.
			</p>
			<AggregatorSection />
			<MemberLookup />
		</main>
	);
}
