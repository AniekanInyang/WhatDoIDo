import type { Config } from "tailwindcss";

const config: Config = {
	content: ["./src/**/*.{js,ts,jsx,tsx,mdx}"],
	theme: {
		extend: {
			colors: {
				brand: {
					primary: "#5A2A6A",
					hover: "#492157",
					accent: "#A26CB5",
					bg: "#FBF8FD",
					text: "#2B1633",
					muted: "#6F5A77",
					border: "#E8D8F0",
					surface: "#FFFFFF",
					soft: "#F7F0FB",
					success: "#287A5A",
					warning: "#A15F16",
				},
			},
			boxShadow: {
				soft: "0 12px 36px rgba(15, 23, 42, 0.08)",
			},
		},
	},
	plugins: [],
};

export default config;
