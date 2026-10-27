import dayGridPlugin from "@fullcalendar/daygrid";
import interactionPlugin from "@fullcalendar/interaction";
import FullCalendar from "@fullcalendar/react";
import timeGridPlugin from "@fullcalendar/timegrid";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { useAuth } from "../auth";
import { Button, EmptyState, ErrorText } from "../components";
import { SkeletonList } from "../route-ux";
import {
	BOOK_ERROR_MESSAGE,
	type BookError,
	bookClass,
	bookErrorOf,
	type CalendarEventItem,
	useCalendarEvents,
	useClasses,
} from "../hooks";
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
	const [room, setRoom] = useState<number | null>(null);
	const [selectedId, setSelectedId] = useState<number | null>(null);
	const [error, setError] = useState<BookError | null>(null);

	const events = useCalendarEvents(venue, range, teacher, room);
	const classes = useClasses(venue, range);

	const booking = useMutation({
		mutationFn: (waitlist: boolean) =>
			bookClass(selectedId ?? 0, crypto.randomUUID(), waitlist),
		onSuccess: () => {
			setError(null);
			setSelectedId(null);
			void queryClient.invalidateQueries();
		},
		onError: (failure: unknown) => setError(bookErrorOf(failure)),
	});

	const teachers = useMemo(() => {
		const seen = new Map<number, string>();
		for (const klass of classes.data ?? [])
			seen.set(klass.teacher, klass.teacher_name);
		return [...seen];
	}, [classes.data]);
	const rooms = useMemo(() => {
		const seen = new Map<number, string>();
		for (const klass of classes.data ?? [])
			seen.set(klass.room, klass.room_name);
		return [...seen];
	}, [classes.data]);
	const selected = (events.data ?? []).find((event) => event.id === selectedId);

	if (events.isPending || classes.isPending) return <SkeletonList />;
	if (events.isError) return <ErrorText message="Could not load calendar." />;
	return (
		<main>
			<h1 data-testid="calendar">Calendar</h1>
			<div>
				<label>
					Teacher{" "}
					<select
						data-testid="calendar-teacher-filter"
						value={teacher ?? ""}
						onChange={(change) =>
							setTeacher(
								change.target.value === "" ? null : Number(change.target.value),
							)
						}
					>
						<option value="">All</option>
						{teachers.map(([id, name]) => (
							<option key={id} value={id}>
								{name}
							</option>
						))}
					</select>
				</label>{" "}
				<label>
					Room{" "}
					<select
						data-testid="calendar-room-filter"
						value={room ?? ""}
						onChange={(change) =>
							setRoom(
								change.target.value === "" ? null : Number(change.target.value),
							)
						}
					>
						<option value="">All</option>
						{rooms.map(([id, name]) => (
							<option key={id} value={id}>
								{name}
							</option>
						))}
					</select>
				</label>
			</div>
			{events.data.length === 0 ? (
				<EmptyState message="No classes this week." />
			) : (
				<FullCalendar
					plugins={[dayGridPlugin, timeGridPlugin, interactionPlugin]}
					initialView="timeGridWeek"
					timeZone={timeZone}
					events={calendarEventsForWeek(events.data)}
					datesSet={(info) =>
						setRange({
							from: info.start.toISOString(),
							to: info.end.toISOString(),
						})
					}
					eventClick={(info) => {
						const found = (events.data ?? []).find(
							(event) => event.id === Number(info.event.id),
						);
						if (found?.kind === "class") {
							setSelectedId(found.id);
							setError(null);
						}
					}}
				/>
			)}
			{selected ? (
				<div data-testid="calendar-selection">
					<p>
						{selected.title} —{" "}
						{formatInVenueTimeZone(selected.starts_at, timeZone)}
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
