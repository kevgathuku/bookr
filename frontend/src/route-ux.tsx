import { Component, type ReactNode, useEffect, useRef } from "react";
import { Link, useLocation } from "react-router";

export function SkeletonList({ rows = 3 }: { rows?: number }) {
	return (
		<div aria-busy="true" aria-label="Loading">
			{Array.from({ length: rows }, (_, index) => (
				<div
					// biome-ignore lint/suspicious/noArrayIndexKey: static placeholder rows
					key={index}
					className="my-2 h-6 animate-pulse rounded bg-gray-200"
				/>
			))}
		</div>
	);
}

export function RouteFocus({ children }: { children: ReactNode }) {
	const location = useLocation();
	const first = useRef(true);
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
		<main>
			<h1 data-testid="not-found">Page not found</h1>
			<p>This page does not exist.</p>
			<Link to="/">Back to schedule</Link>
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
				<main>
					<h1 data-testid="error-page">Something went wrong</h1>
					<p>Please try again.</p>
					<button
						type="button"
						onClick={() => this.setState({ failed: false })}
					>
						Retry
					</button>
				</main>
			);
		}
		return this.props.children;
	}
}
