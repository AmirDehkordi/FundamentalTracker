import animate from "tailwindcss-animate";
import type { Config } from "tailwindcss";

// Design tokens are the CSS variables in src/index.css; this file only maps them into Tailwind.
// The one trap: the design skill's token `--accent` (interactive blue) and shadcn/ui's own `accent`
// semantic key (component hover) are different colours. We route the blue through `primary`/`ring`
// and hand shadcn's `accent` key back to surface-2, so stock shadcn components work unmodified while
// the skill's own tokens live under non-colliding keys (surface-*, fg-*, pos/neg/warn, accent-bg,
// ticker-*). See .claude/skills/dashboard-design/SKILL.md.
export default {
  darkMode: ["class"],
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        border: "var(--border)",
        input: "var(--border)",
        ring: "var(--accent)",
        background: "var(--bg)",
        foreground: "var(--text-1)",
        primary: {
          DEFAULT: "var(--accent)",
          foreground: "var(--bg)",
        },
        secondary: {
          DEFAULT: "var(--surface-2)",
          foreground: "var(--text-1)",
        },
        destructive: {
          DEFAULT: "var(--neg)",
          foreground: "var(--bg)",
        },
        muted: {
          DEFAULT: "var(--surface-2)",
          foreground: "var(--text-2)",
        },
        accent: {
          DEFAULT: "var(--surface-2)",
          foreground: "var(--text-1)",
        },
        popover: {
          DEFAULT: "var(--surface-2)",
          foreground: "var(--text-1)",
        },
        card: {
          DEFAULT: "var(--surface-1)",
          foreground: "var(--text-1)",
        },
        bg: "var(--bg)",
        surface: {
          "1": "var(--surface-1)",
          "2": "var(--surface-2)",
        },
        fg: {
          "1": "var(--text-1)",
          "2": "var(--text-2)",
          "3": "var(--text-3)",
        },
        brand: "var(--accent)",
        "accent-bg": "var(--accent-bg)",
        pos: "var(--pos)",
        neg: "var(--neg)",
        warn: "var(--warn)",
        // Per-ticker identity — reassigned off the semantic/accent hues (see src/lib/tickers.ts).
        ticker: {
          nvda: "#6E9BF0",
          msft: "#2DB6A6",
          aapl: "#A78BFA",
          googl: "#CE7CA6",
          etn: "#D68A5A",
        },
      },
      borderRadius: {
        lg: "var(--radius)",
        md: "calc(var(--radius) - 2px)",
        sm: "calc(var(--radius) - 4px)",
      },
      fontFamily: {
        sans: ["Inter", "system-ui", "sans-serif"],
      },
      fontSize: {
        "13": [
          "0.8125rem",
          {
            lineHeight: "1.125rem",
          },
        ],
      },
      keyframes: {
        "accordion-down": {
          from: {
            height: "0",
          },
          to: {
            height: "var(--radix-accordion-content-height)",
          },
        },
        "accordion-up": {
          from: {
            height: "var(--radix-accordion-content-height)",
          },
          to: {
            height: "0",
          },
        },
      },
      animation: {
        "accordion-down": "accordion-down 0.15s ease-out",
        "accordion-up": "accordion-up 0.15s ease-out",
      },
    },
  },
  plugins: [animate],
} satisfies Config;
