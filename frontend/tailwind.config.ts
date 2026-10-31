import type { Config } from "tailwindcss";
import animate from "tailwindcss-animate";

export default {
  darkMode: "class",
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    container: { center: true, padding: "1.5rem" },
    extend: {
      fontFamily: { sans: ["Inter", "IBM Plex Sans", "ui-sans-serif", "system-ui", "-apple-system", "Segoe UI", "sans-serif"], mono: ["IBM Plex Mono", "ui-monospace", "SFMono-Regular", "Menlo", "monospace"] },
      colors: {
        border: "hsl(var(--border))",
        input: "hsl(var(--border))",
        ring: "hsl(var(--ring))",
        background: "hsl(var(--background))",
        foreground: "hsl(var(--foreground))",
        card: { DEFAULT: "hsl(var(--card))", foreground: "hsl(var(--foreground))" },
        muted: { DEFAULT: "hsl(var(--muted))", foreground: "hsl(var(--muted-foreground))" },
        primary: { DEFAULT: "hsl(var(--primary))", foreground: "hsl(var(--primary-foreground))" },
        accent: { DEFAULT: "hsl(var(--accent))", foreground: "hsl(var(--foreground))" },
        destructive: { DEFAULT: "hsl(var(--critical))", foreground: "#fff" },
        sev: { critical: "hsl(var(--critical))", high: "hsl(var(--high))", medium: "hsl(var(--medium))", low: "hsl(var(--low))", ok: "hsl(var(--ok))", info: "hsl(var(--info))" },
      },
      borderRadius: { lg: "0.75rem", md: "0.5rem", sm: "0.375rem" },
      keyframes: { shimmer: { "100%": { transform: "translateX(100%)" } }, pulseDot: { "0%,100%": { opacity: "1" }, "50%": { opacity: ".35" } } },
      animation: { shimmer: "shimmer 1.6s infinite", pulseDot: "pulseDot 1.6s ease-in-out infinite" },
    },
  },
  plugins: [animate],
} satisfies Config;
