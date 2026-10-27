import { type ReactNode, useState } from "react";

export function Button({
	children,
	onClick,
	disabled,
	testId,
}: {
	children: ReactNode;
	onClick?: () => void;
	disabled?: boolean;
	testId?: string;
}) {
	return (
		<button
			type="button"
			data-testid={testId}
			disabled={disabled}
			onClick={onClick}
			className="rounded bg-brand px-4 py-2 text-white disabled:opacity-50"
		>
			{children}
		</button>
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
	return <p className="text-gray-500">{message}</p>;
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
