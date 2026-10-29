import { Component, type ReactNode, useEffect, useRef } from "react";
import { Link, useLocation } from "react-router";
import { Button } from "./components";

export function SkeletonList({ rows = 3 }: { rows?: number }) {
	return (
		<main className="mx-auto max-w-5xl px-6 py-8 lg:px-10">
			<div aria-busy="true" role="status" aria-label="Loading">
				{Array.from({ length: rows }, (_, index) => (
					<div
						// biome-ignore lint/suspicious/noArrayIndexKey: static placeholder rows
						key={index}
						className="my-2 h-6 animate-pulse rounded bg-gray-200"
					/>
				))}
			</div>
		</main>
	);
}

export function RouteFocus({ children }: { children: ReactNode }) {
	const location = useLocation();
	const first = useRef(true);
	// Pathname intentionally re-runs the focus move on every route change; the
	// effect body only needs to run, not to read the value (covered by the
	// route-change focus test).
	// biome-ignore lint/correctness/useExhaustiveDependencies: see above.
	useEffect(() => {
		if (first.current) {
			first.current = false;
			return;
		}
		// Headings are not focusable: move focus to <main> itself so
		// screen readers announce the new route (tabIndex -1 stays out
		// of the tab order).
		const main = document.querySelector("main");
		if (main) {
			(main as HTMLElement).tabIndex = -1;
			(main as HTMLElement).focus({ preventScroll: true });
			main.scrollIntoView?.();
		}
	}, [location.pathname]);
	return <>{children}</>;
}

export function NotFound() {
	return (
		<main className="mx-auto max-w-5xl px-6 py-8 lg:px-10">
			<h1 data-testid="not-found" className="text-3xl font-bold tracking-tight">
				Page not found
			</h1>
			<p className="mt-1 text-sm text-slate-500">This page does not exist.</p>
			<Link
				to="/"
				className="mt-4 inline-block font-semibold text-brand hover:underline"
			>
				Back to schedule
			</Link>
		</main>
	);
}

interface ErrorBoundaryState {
	failed: boolean;
}

export class ErrorBoundary extends Component<
	{ children: ReactNode },
	ErrorBoundaryState
> {
	state: ErrorBoundaryState = { failed: false };

	static getDerivedStateFromError(): ErrorBoundaryState {
		return { failed: true };
	}

	render() {
		if (this.state.failed) {
			return (
				<main className="mx-auto max-w-5xl px-6 py-8 lg:px-10">
					<h1
						data-testid="error-page"
						className="text-3xl font-bold tracking-tight"
					>
						Something went wrong
					</h1>
					<p className="mt-1 text-sm text-slate-500">Please try again.</p>
					<div className="mt-4">
						<Button
							type="button"
							onClick={() => this.setState({ failed: false })}
						>
							Retry
						</Button>
					</div>
				</main>
			);
		}
		return this.props.children;
	}
}
