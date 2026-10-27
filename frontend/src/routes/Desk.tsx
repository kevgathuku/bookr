import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useAuth } from "../auth";
import { Button, EmptyState, ErrorText } from "../components";
import {
	adjustPass,
	cancelBookingOverride,
	checkinBooking,
	noShowBooking,
	type MemberHit,
	type RosterRow,
	searchMembers,
	useDoorEvents,
	useMemberPasses,
	useRoster,
} from "../hooks";
import { formatInVenueTimeZone, useVenue, venueTimeZone } from "../venue";

function todayIso(): string {
	return new Date().toISOString().slice(0, 10);
}

function RosterRowActions({ row }: { row: RosterRow }) {
	const queryClient = useQueryClient();
	const [reason, setReason] = useState("");
	const [error, setError] = useState<string | null>(null);
	const refresh = () => {
		setError(null);
		void queryClient.invalidateQueries({ queryKey: ["desk", "roster"] });
	};
	const fail = () => setError("Action failed. Try again.");
	const checkin = useMutation({
		mutationFn: () => checkinBooking(row.id),
		onSuccess: refresh,
		onError: fail,
	});
	const noShow = useMutation({
		mutationFn: () => noShowBooking(row.id),
		onSuccess: refresh,
		onError: fail,
	});
	const override = useMutation({
		mutationFn: () => cancelBookingOverride(row.id, reason),
		onSuccess: refresh,
		onError: fail,
	});
	const busy = checkin.isPending || noShow.isPending || override.isPending;
	return (
		<span>
			{row.checked_in_at ? (
				<span data-testid={`checked-in-${row.id}`}>Checked in</span>
			) : (
				<Button
					testId={`checkin-button-${row.id}`}
					disabled={busy}
					onClick={() => checkin.mutate()}
				>
					Check in
				</Button>
			)}{" "}
			<Button
				testId={`noshow-button-${row.id}`}
				disabled={busy}
				onClick={() => noShow.mutate()}
			>
				No-show
			</Button>{" "}
			<input
				aria-label={`Override reason for booking ${row.id}`}
				placeholder="Override reason"
				value={reason}
				onChange={(change) => setReason(change.target.value)}
			/>{" "}
			<Button
				testId={`override-button-${row.id}`}
				disabled={busy || reason.trim() === ""}
				onClick={() => override.mutate()}
			>
				Override cancel
			</Button>
			{error ? <ErrorText message={error} /> : null}
		</span>
	);
}

export function MemberLookup() {
	const queryClient = useQueryClient();
	const [query, setQuery] = useState("");
	const [hits, setHits] = useState<MemberHit[]>([]);
	const [member, setMember] = useState<MemberHit | null>(null);
	const [passId, setPassId] = useState("");
	const [delta, setDelta] = useState("1");
	const [reason, setReason] = useState("");
	const [error, setError] = useState<string | null>(null);
	const [done, setDone] = useState<string | null>(null);
	const passes = useMemberPasses(member?.id ?? null);
	const adjust = useMutation({
		mutationFn: () => adjustPass(Number(passId), Number(delta), reason),
		onSuccess: () => {
			setError(null);
			setDone("Adjustment saved.");
			void queryClient.invalidateQueries({ queryKey: ["desk", "passes"] });
		},
		onError: () => {
			setDone(null);
			setError("Adjustment failed. Try again.");
		},
	});

	return (
		<section>
			<h2>Member lookup</h2>
			<form
				onSubmit={(event) => {
					event.preventDefault();
					setMember(null);
					searchMembers(query).then(setHits, () => setHits([]));
				}}
			>
				<input
					data-testid="member-search"
					autoFocus
					placeholder="Username"
					value={query}
					onChange={(change) => setQuery(change.target.value)}
				/>{" "}
				<Button testId="member-search-button" type="submit">
					Search
				</Button>
			</form>
			{hits.length > 0 ? (
				<ul>
					{hits.map((hit) => (
						<li key={hit.id}>
							<Button testId={`member-hit-${hit.id}`} onClick={() => setMember(hit)}>
								{hit.username}
							</Button>
						</li>
					))}
				</ul>
			) : null}
			{member ? (
				<div data-testid="member-panel">
					<p>Adjusting credits for {member.username}</p>
					{passes.data && passes.data.length > 0 ? (
						<form
							onSubmit={(event) => {
								event.preventDefault();
								adjust.mutate();
							}}
						>
							<select
								data-testid="adjust-pass"
								value={passId}
								onChange={(change) => setPassId(change.target.value)}
							>
								<option value="">Pick a pass</option>
								{passes.data.map((pass) => (
									<option key={pass.id} value={pass.id}>
										{pass.product_name} ({pass.credits_total - pass.credits_used} left)
									</option>
								))}
							</select>{" "}
							<input
								data-testid="adjust-delta"
								type="number"
								value={delta}
								onChange={(change) => setDelta(change.target.value)}
							/>{" "}
							<input
								data-testid="adjust-reason"
								placeholder="Reason"
								value={reason}
								onChange={(change) => setReason(change.target.value)}
							/>{" "}
							<Button
								testId="adjust-button"
								type="submit"
								disabled={
									adjust.isPending ||
									passId === "" ||
									Number(delta) === 0 ||
									reason.trim() === ""
								}
							>
								Adjust
							</Button>
						</form>
					) : (
						<EmptyState message="No passes for this member." />
					)}
					{error ? <ErrorText message={error} /> : null}
					{done ? <p>{done}</p> : null}
				</div>
			) : null}
		</section>
	);
}

export default function Desk() {
	const { venue } = useVenue();
	const { me } = useAuth();
	const timeZone = venueTimeZone(me, venue);
	const [date, setDate] = useState(todayIso);
	const roster = useRoster(date);
	const doors = useDoorEvents();

	return (
		<main>
			<h1 data-testid="desk">Front desk</h1>
			<section>
				<h2>Roster</h2>
				<input
					data-testid="roster-date"
					type="date"
					value={date}
					onChange={(change) => setDate(change.target.value)}
				/>
				{roster.isPending ? (
					<p>Loading roster…</p>
				) : roster.isError ? (
					<ErrorText message="Could not load roster." />
				) : roster.data.length === 0 ? (
					<EmptyState message="No bookings this day." />
				) : (
					<ul>
						{roster.data.map((row) => (
							<li key={row.id} data-testid="roster-row">
								<span>
									{row.member} — {row.class_title} —{" "}
									{formatInVenueTimeZone(row.starts_at, timeZone)} — {row.status}
								</span>{" "}
								<RosterRowActions row={row} />
							</li>
						))}
					</ul>
				)}
			</section>
			<MemberLookup />
			<section>
				<h2>Door log</h2>
				{doors.isPending ? (
					<p>Loading door log…</p>
				) : doors.isError ? (
					<ErrorText message="Could not load door log." />
				) : doors.data.length === 0 ? (
					<EmptyState message="No door events yet." />
				) : (
					<ul>
						{doors.data.slice(0, 10).map((event) => (
							<li key={event.id} data-testid="door-row">
								{event.granted ? "Granted" : "Denied"} — {event.reason}
							</li>
						))}
					</ul>
				)}
			</section>
		</main>
	);
}
