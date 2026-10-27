import { useMemo } from "react";
import { useAuth } from "../auth";
import { EmptyState, ErrorText } from "../components";
import { useCalendarEvents, useClasses, useSubstitutions } from "../hooks";
import { formatInVenueTimeZone, useVenue, venueTimeZone } from "../venue";

export default function Teach() {
	const { venue } = useVenue();
	const { me } = useAuth();
	const timeZone = venueTimeZone(me, venue);
	const classes = useClasses(venue);
	const range = useMemo(() => {
		const from = new Date();
		const to = new Date(from.getTime() + 7 * 24 * 3600 * 1000);
		return { from: from.toISOString(), to: to.toISOString() };
	}, []);
	const appointments = useCalendarEvents(venue, range, me?.id ?? null, null);
	const subs = useSubstitutions();

	if (classes.isPending || appointments.isPending || subs.isPending)
		return <p>Loading teaching schedule…</p>;
	if (classes.isError || appointments.isError || subs.isError)
		return <ErrorText message="Could not load teaching schedule." />;
	const mine = (classes.data ?? []).filter((klass) => klass.teacher === me?.id);
	const mineAppointments = (appointments.data ?? []).filter(
		(event) => event.kind === "appointment",
	);
	const mySubs = (subs.data ?? []).filter(
		(sub) => sub.old_teacher === me?.id || sub.new_teacher === me?.id,
	);
	return (
		<main>
			<h1 data-testid="teach">Teaching schedule</h1>
			<section>
				<h2>My classes</h2>
				{mine.length === 0 ? (
					<EmptyState message="No classes assigned this week." />
				) : (
					<ul>
						{mine.map((klass) => (
							<li key={klass.id} data-testid="teach-class-row">
								{klass.class_type_name} — {klass.room_name} —{" "}
								{formatInVenueTimeZone(klass.starts_at, timeZone)}
							</li>
						))}
					</ul>
				)}
			</section>
			<section>
				<h2>My appointments</h2>
				{mineAppointments.length === 0 ? (
					<EmptyState message="No appointments this week." />
				) : (
					<ul>
						{mineAppointments.map((event) => (
							<li key={event.id} data-testid="teach-appointment-row">
								{event.title} — {formatInVenueTimeZone(event.starts_at, timeZone)}
							</li>
						))}
					</ul>
				)}
			</section>
			<section>
				<h2>Substitution history</h2>
				{mySubs.length === 0 ? (
					<EmptyState message="No substitutions involving you." />
				) : (
					<ul>
						{mySubs.map((sub) => (
							<li key={sub.id} data-testid="teach-sub-row">
								Class {sub.scheduled_class}: {sub.old_teacher_name} →{" "}
								{sub.new_teacher_name}
							</li>
						))}
					</ul>
				)}
			</section>
		</main>
	);
}
