import { type ReactNode, useState } from "react";

export function Button({
	children,
	onClick,
	disabled,
	testId,
	type = "button",
	variant = "primary",
	className,
}: {
	children: ReactNode;
	onClick?: () => void;
	disabled?: boolean;
	testId?: string;
	type?: "button" | "submit";
	variant?: "primary" | "outline";
	className?: string;
}) {
	return (
		<button
			type={type}
			data-testid={testId}
			disabled={disabled}
			onClick={onClick}
			className={
				variant === "outline"
					? `rounded-lg border border-brand px-4 py-2 font-semibold text-brand hover:bg-indigo-50 disabled:opacity-50 ${className ?? ""}`
					: `rounded-lg bg-brand px-4 py-2 font-semibold text-white hover:bg-brand-dark disabled:opacity-50 ${className ?? ""}`
			}
		>
			{children}
		</button>
	);
}

const PILL_TONES = {
	brand: "bg-indigo-100 text-brand-dark",
	ok: "bg-emerald-50 text-ok",
	warn: "bg-amber-50 text-warn",
	bad: "bg-red-50 text-bad",
} as const;

export function Pill({
	tone,
	children,
	testId,
}: {
	tone: keyof typeof PILL_TONES;
	children: ReactNode;
	testId?: string;
}) {
	return (
		<span
			data-testid={testId}
			className={`rounded-full px-2 py-0.5 text-xs font-semibold ${PILL_TONES[tone]}`}
		>
			{children}
		</span>
	);
}

export function Field({
	label,
	htmlFor,
	children,
}: {
	label: string;
	htmlFor: string;
	children: ReactNode;
}) {
	return (
		<label className="block" htmlFor={htmlFor}>
			<span className="block text-sm font-medium">{label}</span>
			{children}
		</label>
	);
}

export function EmptyState({ message }: { message: string }) {
	return <p className="py-8 text-center text-slate-500">{message}</p>;
}

export function ErrorText({ message }: { message: string }) {
	return (
		<p role="alert" className="text-bad">
			{message}
		</p>
	);
}

export function useError(): [string | null, (message: string | null) => void] {
	return useState<string | null>(null);
}
