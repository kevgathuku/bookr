import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { canBook, useAuth } from "../auth";
import { Button, EmptyState, ErrorText, Pill } from "../components";
import {
	BOOK_ERROR_MESSAGE,
	type BookError,
	bookErrorOf,
	bookSession,
	type SessionItem,
	useBookings,
	useSessions,
} from "../hooks";
import { SkeletonList } from "../route-ux";
import { useVenue, venueTimeZone } from "../venue";

const DAY_MS = 86400000;

function startOfToday(): Date {
	const now = new Date();
	now.setHours(0, 0, 0, 0);
	return now;
}

function dayKey(date: Date, timeZone: string): string {
	return new Intl.DateTimeFormat("en-CA", {
		timeZone,
		year: "numeric",
		month: "2-digit",
		day: "2-digit",
	}).format(date);
}

function dayLabel(date: Date, timeZone: string): string {
	return new Intl.DateTimeFormat("en-GB", {
		timeZone,
		weekday: "long",
		month: "short",
		day: "numeric",
	}).format(date);
}

function formatTime(iso: string, timeZone: string): string {
	return new Intl.DateTimeFormat("en-GB", {
		timeZone,
		hour: "2-digit",
		minute: "2-digit",
		hour12: false,
	}).format(new Date(iso));
}

function durationMin(klass: SessionItem): number {
	return Math.round(
		(new Date(klass.ends_at).getTime() - new Date(klass.starts_at).getTime()) /
			60000,
	);
}

function Availability({ klass }: { klass: SessionItem }) {
	if (klass.spots_left === null || klass.spots_left === undefined) return null;
	if (klass.spots_left <= 0) return <Pill tone="bad">Full</Pill>;
	if (klass.spots_left <= 3)
		return <Pill tone="warn">Only {klass.spots_left} left</Pill>;
	return <Pill tone="ok">{klass.spots_left} spots left</Pill>;
}

function CapacityMeter({ klass }: { klass: SessionItem }) {
	if (klass.capacity === null || klass.spots_left === null) return null;
	if (klass.capacity <= 0) return null;
	const taken = Math.min(
		1,
		Math.max(0, (klass.capacity - klass.spots_left) / klass.capacity),
	);
	const bar =
		klass.spots_left <= 0 ? "bg-bad" : taken >= 0.85 ? "bg-warn" : "bg-ok";
	return (
		<div className="mt-2 h-1.5 w-48 rounded-full bg-stone-200">
			<div
				className={`h-full rounded-full ${bar}`}
				style={{ width: `${taken * 100}%` }}
			/>
		</div>
	);
}

function ClassRow({
	klass,
	booked,
	timeZone,
	mayBook,
}: {
	klass: SessionItem;
	booked: boolean;
	timeZone: string;
	mayBook: boolean;
}) {
	const queryClient = useQueryClient();
	const [error, setError] = useState<BookError | null>(null);
	const booking = useMutation({
		mutationFn: (waitlist: boolean) => bookSession(klass.id, waitlist),
		onSuccess: () => {
			setError(null);
			void queryClient.invalidateQueries();
		},
		onError: (failure: unknown) => setError(bookErrorOf(failure)),
	});

	return (
		<li
			data-testid="class-row"
			className={`flex items-center gap-5 rounded-2xl border bg-white p-4 shadow-sm ${
				booked ? "border-brand" : "border-slate-200"
			}`}
		>
			<div className="w-24 shrink-0 text-center">
				<p className="text-lg font-bold tabular-nums">
					{formatTime(klass.starts_at, timeZone)}
				</p>
				<p className="text-xs text-slate-500 tabular-nums">
					{formatTime(klass.ends_at, timeZone)} · {durationMin(klass)} min
				</p>
			</div>
			<div className="h-12 w-px bg-slate-200" />
			<div className="min-w-0 flex-1">
				<p className="font-semibold">
					{klass.offering_title}{" "}
					{booked ? (
						<Pill tone="brand" testId="booked-badge">
							Booked
						</Pill>
					) : (
						<Availability klass={klass} />
					)}
				</p>
				<p className="mt-0.5 text-sm text-slate-500">{klass.teacher_name}</p>
				{booked ? null : <CapacityMeter klass={klass} />}
			</div>
			<div className="shrink-0 text-right">
				{booked || !mayBook ? null : (
					<>
						<p className="text-sm text-slate-500">1 credit</p>
						<Button
							testId={`book-button-${klass.id}`}
							disabled={booking.isPending}
							onClick={() => booking.mutate(false)}
						>
							Book
						</Button>
						{error === "full" ? (
							<Button
								testId={`waitlist-button-${klass.id}`}
								variant="outline"
								disabled={booking.isPending}
								onClick={() => booking.mutate(true)}
							>
								Join waitlist
							</Button>
						) : null}
					</>
				)}
			</div>
			{error && error !== "full" ? (
				<ErrorText message={BOOK_ERROR_MESSAGE[error]} />
			) : null}
		</li>
	);
}

export default function Schedule({ venue }: { venue: string | null }) {
	const { me } = useAuth();
	const { venue: activeVenue } = useVenue();
	const resolvedVenue = venue ?? activeVenue;
	const timeZone = venueTimeZone(me, resolvedVenue);
	const [anchor, setAnchor] = useState(startOfToday);
	const [selectedKey, setSelectedKey] = useState<string | null>(null);
	const [teacher, setTeacher] = useState<number | null>(null);
	const [onlyBookable, setOnlyBookable] = useState(false);

	const range = useMemo(
		() => ({
			from: anchor.toISOString(),
			to: new Date(anchor.getTime() + 7 * DAY_MS).toISOString(),
		}),
		[anchor],
	);
	const sessions = useSessions(resolvedVenue, range);
	const bookings = useBookings();

	const days = useMemo(() => {
		const out: { date: Date; key: string }[] = [];
		for (let index = 0; index < 7; index++) {
			const date = new Date(anchor.getTime() + index * DAY_MS);
			out.push({ date, key: dayKey(date, timeZone) });
		}
		return out;
	}, [anchor, timeZone]);

	const grouped = useMemo(() => {
		const groups = new Map<string, SessionItem[]>();
		for (const klass of sessions.data ?? []) {
			if (teacher !== null && klass.teacher !== teacher) continue;
			if (onlyBookable && klass.spots_left !== null && klass.spots_left <= 0)
				continue;
			const key = dayKey(new Date(klass.starts_at), timeZone);
			const list = groups.get(key) ?? [];
			list.push(klass);
			groups.set(key, list);
		}
		return [...groups.entries()]
			.map(([key, list]) => ({
				key,
				date: new Date(list[0].starts_at),
				list: list.sort((a, b) => a.starts_at.localeCompare(b.starts_at)),
			}))
			.sort((a, b) => a.key.localeCompare(b.key));
	}, [sessions.data, teacher, onlyBookable, timeZone]);

	// Default to the earliest day that has classes, so a fresh week lands
	// on something bookable instead of an empty today.
	const effectiveKey =
		selectedKey ?? grouped[0]?.key ?? dayKey(new Date(), timeZone);
	const visible = grouped.filter((group) => group.key === effectiveKey);

	const teachers = useMemo(() => {
		const seen = new Map<number, string>();
		for (const klass of sessions.data ?? [])
			seen.set(klass.teacher, klass.teacher_name);
		return [...seen];
	}, [sessions.data]);

	if (sessions.isPending || bookings.isPending) return <SkeletonList />;
	if (sessions.isError) return <ErrorText message="Could not load sessions." />;
	if (bookings.isError) return <ErrorText message="Could not load bookings." />;
	const bookedIds = new Set(
		(bookings.data ?? [])
			.filter((b) => b.status === "booked" || b.status === "waitlisted")
			.map((b) => b.session),
	);

	return (
		<main className="mx-auto max-w-5xl px-6 py-8 lg:px-10">
			<div className="flex items-end justify-between">
				<div>
					<h1
						data-testid="schedule"
						className="text-3xl font-bold tracking-tight"
					>
						Schedule
					</h1>
					<p className="mt-1 text-sm text-slate-500">
						7 days from {dayLabel(anchor, timeZone)} · shown in venue time
					</p>
				</div>
				<div className="flex gap-2">
					<button
						type="button"
						onClick={() => {
							setAnchor(new Date(anchor.getTime() - 7 * DAY_MS));
							setSelectedKey(null);
						}}
						className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-medium hover:bg-stone-50"
					>
						&larr; Prev
					</button>
					<button
						type="button"
						onClick={() => {
							setAnchor(new Date(anchor.getTime() + 7 * DAY_MS));
							setSelectedKey(null);
						}}
						className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-medium hover:bg-stone-50"
					>
						Next &rarr;
					</button>
				</div>
			</div>

			<div className="mt-5 flex gap-2" role="tablist" aria-label="Days">
				{days.map(({ date, key }) => {
					const active = key === effectiveKey;
					return (
						<button
							key={key}
							type="button"
							role="tab"
							aria-selected={active}
							onClick={() => setSelectedKey(key)}
							className={`flex-1 rounded-xl px-2 py-2 text-center ${
								active
									? "bg-slate-900 text-white"
									: "border border-slate-200 bg-white hover:border-slate-400"
							}`}
						>
							<span
								className={`block text-[11px] uppercase tracking-wider ${
									active ? "opacity-70" : "text-slate-500"
								}`}
							>
								{new Intl.DateTimeFormat("en-GB", {
									timeZone,
									weekday: "short",
								}).format(date)}
							</span>
							<span className="block text-lg font-bold">
								{new Intl.DateTimeFormat("en-GB", {
									timeZone,
									day: "numeric",
								}).format(date)}
							</span>
						</button>
					);
				})}
			</div>

			<div className="mt-4 flex items-center gap-3 text-sm">
				<label className="flex items-center gap-2 rounded-lg border border-slate-300 bg-white px-3 py-2">
					Teacher
					<select
						data-testid="schedule-teacher-filter"
						value={teacher ?? ""}
						onChange={(change) =>
							setTeacher(
								change.target.value === "" ? null : Number(change.target.value),
							)
						}
						className="bg-transparent font-medium outline-none"
					>
						<option value="">All</option>
						{teachers.map(([id, name]) => (
							<option key={id} value={id}>
								{name}
							</option>
						))}
					</select>
				</label>
				<label className="ml-auto flex items-center gap-2 text-slate-600">
					{canBook(me, resolvedVenue) ? (
						<>
							<input
								type="checkbox"
								checked={onlyBookable}
								onChange={(change) => setOnlyBookable(change.target.checked)}
								className="h-4 w-4 accent-[#4f46e5]"
							/>
							Only bookable
						</>
					) : null}
				</label>
			</div>

			{visible.length === 0 ? (
				<div className="mt-8">
					<EmptyState message="No sessions this week." />
				</div>
			) : (
				visible.map((group) => (
					<section key={group.key}>
						<h2 className="mt-8 text-sm font-bold uppercase tracking-widest text-slate-500">
							{dayLabel(group.date, timeZone)}
						</h2>
						<ul className="mt-3 space-y-3">
							{group.list.map((klass) => (
								<ClassRow
									key={klass.id}
									klass={klass}
									booked={bookedIds.has(klass.id)}
									timeZone={timeZone}
									mayBook={canBook(me, resolvedVenue)}
								/>
							))}
						</ul>
					</section>
				))
			)}
		</main>
	);
}
