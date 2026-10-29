import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { Button, EmptyState, ErrorText } from "../components";
import {
	activatePolicy,
	type ClassTypeItem,
	createClass,
	createProduct,
	createStaffAggregator,
	createSubstitution,
	deleteClass,
	type ProductItem,
	patchProduct,
	rotateStaffAggregator,
	useAggEvents,
	useClasses,
	useClassTypes,
	usePolicies,
	useProducts,
	useRooms,
	useStaffAggregators,
	useSubstitutions,
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

function ClassSection() {
	const classes = useClasses(null);
	const rooms = useRooms();
	const types = useClassTypes();
	const tools = useRefresh(["venue"]);
	const [form, setForm] = useState({
		class_type: "",
		room: "",
		teacher: "",
		starts_at: "",
		ends_at: "",
	});
	const teachers = useMemo(() => {
		const seen = new Map<number, string>();
		for (const klass of classes.data ?? [])
			seen.set(klass.teacher, klass.teacher_name);
		return [...seen];
	}, [classes.data]);
	const create = useMutation({
		mutationFn: () =>
			createClass({
				class_type: Number(form.class_type),
				room: Number(form.room),
				teacher: Number(form.teacher),
				starts_at: new Date(form.starts_at).toISOString(),
				ends_at: new Date(form.ends_at).toISOString(),
			}),
		onSuccess: tools.refresh,
		onError: tools.fail,
	});
	const remove = useMutation({
		mutationFn: (id: number) => deleteClass(id),
		onSuccess: tools.refresh,
		onError: tools.fail,
	});
	const set = (key: keyof typeof form) => (value: string) =>
		setForm((prior) => ({ ...prior, [key]: value }));

	return (
		<section className="mt-8">
			<h2 className="text-lg font-semibold">Classes</h2>
			<form
				className="mt-3 flex flex-wrap items-center gap-2"
				onSubmit={(event) => {
					event.preventDefault();
					create.mutate();
				}}
			>
				<select
					data-testid="class-form-type"
					value={form.class_type}
					onChange={(change) => set("class_type")(change.target.value)}
				>
					<option value="">Type</option>
					{(types.data ?? []).map((type: ClassTypeItem) => (
						<option key={type.id} value={type.id}>
							{type.name}
						</option>
					))}
				</select>{" "}
				<select
					data-testid="class-form-room"
					value={form.room}
					onChange={(change) => set("room")(change.target.value)}
				>
					<option value="">Room</option>
					{(rooms.data ?? []).map((room) => (
						<option key={room.id} value={room.id}>
							{room.name}
						</option>
					))}
				</select>{" "}
				<select
					data-testid="class-form-teacher"
					value={form.teacher}
					onChange={(change) => set("teacher")(change.target.value)}
				>
					<option value="">Teacher</option>
					{teachers.map(([id, name]) => (
						<option key={id} value={id}>
							{name}
						</option>
					))}
				</select>{" "}
				<input
					data-testid="class-form-start"
					type="datetime-local"
					value={form.starts_at}
					onChange={(change) => set("starts_at")(change.target.value)}
				/>{" "}
				<input
					data-testid="class-form-end"
					type="datetime-local"
					value={form.ends_at}
					onChange={(change) => set("ends_at")(change.target.value)}
				/>{" "}
				<Button
					testId="class-create-button"
					type="submit"
					disabled={create.isPending}
				>
					Create class
				</Button>
			</form>
			{(classes.data ?? []).length === 0 ? (
				<EmptyState message="No classes this week." />
			) : (
				<ul className="mt-3 space-y-3">
					{(classes.data ?? []).map((klass) => (
						<li
							key={klass.id}
							data-testid="manage-class-row"
							className="flex items-center gap-5 rounded-2xl border border-slate-200 bg-white p-4 shadow-sm"
						>
							<span className="min-w-0 flex-1 font-semibold">
								{klass.class_type_name} — {klass.room_name}{" "}
								<span className="font-normal text-slate-500">
									{klass.status}
								</span>
							</span>{" "}
							<Button
								testId={`class-delete-${klass.id}`}
								disabled={remove.isPending}
								onClick={() => remove.mutate(klass.id)}
							>
								Delete
							</Button>
						</li>
					))}
				</ul>
			)}
			{tools.error ? <ErrorText message={tools.error} /> : null}
		</section>
	);
}

function SubSection() {
	const subs = useSubstitutions();
	const classes = useClasses(null);
	const tools = useRefresh(["manage", "substitutions"]);
	const [classId, setClassId] = useState("");
	const [teacher, setTeacher] = useState("");
	const teachers = useMemo(() => {
		const seen = new Map<number, string>();
		for (const klass of classes.data ?? [])
			seen.set(klass.teacher, klass.teacher_name);
		return [...seen];
	}, [classes.data]);
	const create = useMutation({
		mutationFn: () => createSubstitution(Number(classId), Number(teacher)),
		onSuccess: tools.refresh,
		onError: tools.fail,
	});

	return (
		<section className="mt-8">
			<h2 className="text-lg font-semibold">Substitutions</h2>
			<form
				className="mt-3 flex flex-wrap items-center gap-2"
				onSubmit={(event) => {
					event.preventDefault();
					create.mutate();
				}}
			>
				<select
					data-testid="sub-form-class"
					value={classId}
					onChange={(change) => setClassId(change.target.value)}
				>
					<option value="">Class</option>
					{(classes.data ?? []).map((klass) => (
						<option key={klass.id} value={klass.id}>
							{klass.class_type_name} — {klass.starts_at}
						</option>
					))}
				</select>{" "}
				<select
					data-testid="sub-form-teacher"
					value={teacher}
					onChange={(change) => setTeacher(change.target.value)}
				>
					<option value="">New teacher</option>
					{teachers.map(([id, name]) => (
						<option key={id} value={id}>
							{name}
						</option>
					))}
				</select>{" "}
				<Button
					testId="sub-create-button"
					type="submit"
					disabled={create.isPending}
				>
					Assign substitute
				</Button>
			</form>
			<ul className="mt-3 space-y-3">
				{(subs.data ?? []).map((sub) => (
					<li
						key={sub.id}
						data-testid="sub-row"
						className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm"
					>
						Class {sub.scheduled_class}: {sub.old_teacher} → {sub.new_teacher}
					</li>
				))}
			</ul>
			{tools.error ? <ErrorText message={tools.error} /> : null}
		</section>
	);
}

function ProductRow({ product }: { product: ProductItem }) {
	const queryClient = useQueryClient();
	const [name, setName] = useState(product.name);
	const [error, setError] = useState<string | null>(null);
	const rename = useMutation({
		mutationFn: () => patchProduct(product.id, { name }),
		onSuccess: () => {
			setError(null);
			void queryClient.invalidateQueries({ queryKey: ["manage", "products"] });
		},
		onError: () => setError("Rename failed. Try again."),
	});
	return (
		<li
			data-testid="product-row"
			className="flex flex-wrap items-center gap-2 rounded-2xl border border-slate-200 bg-white p-4 shadow-sm"
		>
			<input
				data-testid={`product-name-${product.id}`}
				value={name}
				onChange={(change) => setName(change.target.value)}
			/>{" "}
			<span>({product.credits_total} credits)</span>{" "}
			<Button
				testId={`product-save-${product.id}`}
				disabled={rename.isPending || name.trim() === ""}
				onClick={() => rename.mutate()}
			>
				Save
			</Button>
			{error ? <ErrorText message={error} /> : null}
		</li>
	);
}

function ProductSection() {
	const products = useProducts();
	const tools = useRefresh(["manage", "products"]);
	const [name, setName] = useState("");
	const [credits, setCredits] = useState("10");
	const [days, setDays] = useState("30");
	const create = useMutation({
		mutationFn: () =>
			createProduct({
				name,
				credits_total: Number(credits),
				validity_days: Number(days),
			}),
		onSuccess: tools.refresh,
		onError: tools.fail,
	});
	return (
		<section className="mt-8">
			<h2 className="text-lg font-semibold">Pass products</h2>
			<form
				className="mt-3 flex flex-wrap items-center gap-2"
				onSubmit={(event) => {
					event.preventDefault();
					create.mutate();
				}}
			>
				<input
					data-testid="product-form-name"
					placeholder="Name"
					value={name}
					onChange={(change) => setName(change.target.value)}
				/>{" "}
				<input
					data-testid="product-form-credits"
					type="number"
					value={credits}
					onChange={(change) => setCredits(change.target.value)}
				/>{" "}
				<input
					data-testid="product-form-days"
					type="number"
					value={days}
					onChange={(change) => setDays(change.target.value)}
				/>{" "}
				<Button
					testId="product-create-button"
					type="submit"
					disabled={create.isPending}
				>
					Create product
				</Button>
			</form>
			<ul className="mt-3 space-y-3">
				{(products.data ?? []).map((product) => (
					<ProductRow key={product.id} product={product} />
				))}
			</ul>
			{tools.error ? <ErrorText message={tools.error} /> : null}
		</section>
	);
}

function PolicySection() {
	const policies = usePolicies();
	const tools = useRefresh(["manage", "policies"]);
	const [hours, setHours] = useState("8");
	const activate = useMutation({
		mutationFn: () =>
			activatePolicy({ class_late_cancel_hours: Number(hours) }),
		onSuccess: tools.refresh,
		onError: tools.fail,
	});

	return (
		<section className="mt-8">
			<h2 className="text-lg font-semibold">
				Policies (history, never edited)
			</h2>
			<form
				className="mt-3 flex flex-wrap items-center gap-2"
				onSubmit={(event) => {
					event.preventDefault();
					activate.mutate();
				}}
			>
				<input
					data-testid="policy-form-hours"
					type="number"
					value={hours}
					onChange={(change) => setHours(change.target.value)}
				/>{" "}
				<Button
					testId="policy-activate-button"
					type="submit"
					disabled={activate.isPending}
				>
					Activate new version
				</Button>
			</form>
			<ul className="mt-3 space-y-3">
				{(policies.data ?? []).map((policy) => (
					<li
						key={policy.id}
						data-testid="policy-row"
						className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm"
					>
						{policy.valid_from} → {policy.valid_until ?? "open"} (
						{policy.class_late_cancel_hours}h)
					</li>
				))}
			</ul>
			{tools.error ? <ErrorText message={tools.error} /> : null}
		</section>
	);
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
				Classes, subs, products, policy versions, aggregators.
			</p>
			<ClassSection />
			<SubSection />
			<ProductSection />
			<PolicySection />
			<AggregatorSection />
			<MemberLookup />
		</main>
	);
}
