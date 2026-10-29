import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// https://vite.dev/config/
export default defineConfig({
	plugins: [react(), tailwindcss()],
	server: {
		proxy: {
			"/api": "http://localhost:8000",
		},
	},
	preview: {
		port: 4173,
		proxy: {
			"/api": "http://localhost:8000",
		},
	},
	test: {
		environment: "jsdom",
		setupFiles: ["./src/test/setup.ts"],
		env: { TZ: "UTC" },
	},
});
