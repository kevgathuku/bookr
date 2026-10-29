import type { ReactNode } from "react";
import { useMemo } from "react";
import { useAuth } from "../auth";
import { EmptyState, ErrorText } from "../components";
import { useCalendarEvents, useClasses, useSubstitutions } from "../hooks";
import { SkeletonList } from "../route-ux";
import { formatInVenueTimeZone, useVenue, venueTimeZone } from "../venue";

function Section({ title, children }: { title: string; children: ReactNode }) {
	return (
		<section className="mt-8">
			<h2 className="text-lg font-semibold">{title}</h2>
			<div className="mt-3">{children}</div>
		</section>
	);
}

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
		return <SkeletonList />;
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
		<main className="mx-auto max-w-5xl px-6 py-8 lg:px-10">
			<h1 data-testid="teach" className="text-3xl font-bold tracking-tight">
				Teaching schedule
			</h1>
			<p className="mt-1 text-sm text-slate-500">
				Your classes, appointments, and cover history for the next 7 days.
			</p>
			<Section title="My classes">
				{mine.length === 0 ? (
					<EmptyState message="No classes assigned this week." />
				) : (
					<ul className="space-y-3">
						{mine.map((klass) => (
							<li
								key={klass.id}
								data-testid="teach-class-row"
								className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm"
							>
								<p className="font-semibold">{klass.class_type_name}</p>
								<p className="mt-0.5 text-sm text-slate-500">
									{klass.room_name} ·{" "}
									{formatInVenueTimeZone(klass.starts_at, timeZone)}
								</p>
							</li>
						))}
					</ul>
				)}
			</Section>
			<Section title="My appointments">
				{mineAppointments.length === 0 ? (
					<EmptyState message="No appointments this week." />
				) : (
					<ul className="space-y-3">
						{mineAppointments.map((event) => (
							<li
								key={event.id}
								data-testid="teach-appointment-row"
								className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm"
							>
								<p className="font-semibold">{event.title}</p>
								<p className="mt-0.5 text-sm text-slate-500">
									{formatInVenueTimeZone(event.starts_at, timeZone)}
								</p>
							</li>
						))}
					</ul>
				)}
			</Section>
			<Section title="Substitution history">
				{mySubs.length === 0 ? (
					<EmptyState message="No substitutions involving you." />
				) : (
					<ul className="space-y-3">
						{mySubs.map((sub) => (
							<li
								key={sub.id}
								data-testid="teach-sub-row"
								className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm"
							>
								Class {sub.scheduled_class}: {sub.old_teacher_name} →{" "}
								{sub.new_teacher_name}
							</li>
						))}
					</ul>
				)}
			</Section>
		</main>
	);
}
