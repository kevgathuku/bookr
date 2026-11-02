import dayGridPlugin from "@fullcalendar/daygrid";
import interactionPlugin from "@fullcalendar/interaction";
import momentTimezonePlugin from "@fullcalendar/moment-timezone";
import FullCalendar from "@fullcalendar/react";
import timeGridPlugin from "@fullcalendar/timegrid";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useCallback, useMemo, useState } from "react";
import { useAuth } from "../auth";
import { Button, ErrorText } from "../components";
import {
	BOOK_ERROR_MESSAGE,
	type BookError,
	bookErrorOf,
	bookSession,
	type CalendarEventItem,
	useCalendarEvents,
	useSessions,
} from "../hooks";
import { SkeletonList } from "../route-ux";
import { formatInVenueTimeZone, useVenue, venueTimeZone } from "../venue";

function currentWeekRange(): { from: string; to: string } {
	const from = new Date();
	const to = new Date(from.getTime() + 7 * 24 * 3600 * 1000);
	return { from: from.toISOString(), to: to.toISOString() };
}

export function calendarEventsForWeek(
	classes: CalendarEventItem[] | undefined,
): { id: string; title: string; start: string; end: string; kind: string }[] {
	return (classes ?? []).map((event) => ({
		id: String(event.id),
		title: event.title,
		start: event.starts_at,
		end: event.ends_at,
		kind: event.kind,
	}));
}

export default function Calendar() {
	const { venue } = useVenue();
	const { me } = useAuth();
	const timeZone = venueTimeZone(me, venue);
	const queryClient = useQueryClient();
	const [range, setRange] = useState(currentWeekRange);
	const [teacher, setTeacher] = useState<number | null>(null);
	const [selectedId, setSelectedId] = useState<number | null>(null);
	const [error, setError] = useState<BookError | null>(null);

	const events = useCalendarEvents(venue, range, teacher);
	const sessions = useSessions(venue, range);

	const booking = useMutation({
		mutationFn: (waitlist: boolean) => bookSession(selectedId ?? 0, waitlist),
		onSuccess: () => {
			setError(null);
			setSelectedId(null);
			void queryClient.invalidateQueries();
		},
		onError: (failure: unknown) => setError(bookErrorOf(failure)),
	});

	const teachers = useMemo(() => {
		const seen = new Map<number, string>();
		for (const klass of sessions.data ?? [])
			seen.set(klass.teacher, klass.teacher_name);
		return [...seen];
	}, [sessions.data]);
	const calendarEvents = useMemo(
		() => calendarEventsForWeek(events.data),
		[events.data],
	);
	const handleDatesSet = useCallback(
		(info: { start: Date; end: Date }) =>
			setRange({
				from: info.start.toISOString(),
				to: info.end.toISOString(),
			}),
		[],
	);
	const handleEventClick = useCallback(
		(info: { event: { id: string } }) => {
			const found = (events.data ?? []).find(
				(event) => event.id === Number(info.event.id),
			);
			// Sessions are selectable; booking them wires up in .3.
			if (found?.kind === "session") {
				setSelectedId(found.id);
				setError(null);
			}
		},
		[events.data],
	);
	const selected = (events.data ?? []).find((event) => event.id === selectedId);

	if (events.isPending || sessions.isPending) return <SkeletonList />;
	if (events.isError) return <ErrorText message="Could not load calendar." />;
	return (
		<main className="mx-auto max-w-5xl px-6 py-8 lg:px-10">
			<h1 data-testid="calendar" className="text-3xl font-bold tracking-tight">
				Calendar
			</h1>
			<p className="mt-1 text-sm text-slate-500">
				Week grid in venue time — pick an event to book it.
			</p>
			<div className="mt-4 flex items-center gap-3 text-sm">
				<label className="flex items-center gap-2 rounded-lg border border-slate-300 bg-white px-3 py-2">
					Teacher{" "}
					<select
						data-testid="calendar-teacher-filter"
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
			</div>
			{/* The grid itself is the empty state: an eventless week still
				needs its toolbar so members can navigate back. */}
			<FullCalendar
				key={timeZone}
				plugins={[
					dayGridPlugin,
					timeGridPlugin,
					interactionPlugin,
					momentTimezonePlugin,
				]}
				initialView="timeGridWeek"
				timeZone={timeZone}
				eventColor="#4f46e5"
				events={calendarEvents}
				datesSet={handleDatesSet}
				eventClick={handleEventClick}
			/>
			{selected ? (
				<div
					data-testid="calendar-selection"
					className="mt-4 flex items-center gap-5 rounded-2xl border border-slate-200 bg-white p-4 shadow-sm"
				>
					<p className="min-w-0 flex-1 font-semibold">
						{selected.title} —{" "}
						<span className="font-normal text-slate-500">
							{formatInVenueTimeZone(selected.starts_at, timeZone)}
						</span>
					</p>
					<Button
						testId={`calendar-book-button-${selected.id}`}
						disabled={booking.isPending}
						onClick={() => booking.mutate(false)}
					>
						Book
					</Button>
					{error === "full" ? (
						<Button
							testId={`calendar-waitlist-button-${selected.id}`}
							disabled={booking.isPending}
							onClick={() => booking.mutate(true)}
						>
							Join waitlist
						</Button>
					) : null}
					{error ? <ErrorText message={BOOK_ERROR_MESSAGE[error]} /> : null}
				</div>
			) : null}
		</main>
	);
}
