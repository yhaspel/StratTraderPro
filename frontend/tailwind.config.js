/** @type {import('tailwindcss').Config} */
// "Industry" design system — every color/font/space/radius/shadow maps to the
// CSS custom properties declared in src/styles/tokens.css. Never add a raw hex
// here; retune the tokens instead.
module.exports = {
  content: ["./src/**/*.{html,ts}"],
  theme: {
    extend: {
      colors: {
        // Ground / surfaces / chrome
        bg: "var(--color-bg)",
        surface: "var(--color-surface)",
        ink: "var(--color-text)",
        divider: "var(--color-divider)",
        // Steel accent — machinery: actions, focus, progress, equity
        accent: {
          DEFAULT: "var(--color-accent)",
          100: "var(--color-accent-100)",
          200: "var(--color-accent-200)",
          300: "var(--color-accent-300)",
          400: "var(--color-accent-400)",
          500: "var(--color-accent-500)",
          600: "var(--color-accent-600)",
          700: "var(--color-accent-700)",
          800: "var(--color-accent-800)",
          900: "var(--color-accent-900)",
        },
        neutral: {
          100: "var(--color-neutral-100)",
          200: "var(--color-neutral-200)",
          300: "var(--color-neutral-300)",
          400: "var(--color-neutral-400)",
          500: "var(--color-neutral-500)",
          600: "var(--color-neutral-600)",
          700: "var(--color-neutral-700)",
          800: "var(--color-neutral-800)",
          900: "var(--color-neutral-900)",
        },
        // Trading semantics — money and risk ONLY, never decorative
        up: {
          DEFAULT: "var(--up)",
          tint: "var(--up-tint)",
          deep: "var(--up-deep)",
        },
        down: {
          DEFAULT: "var(--down)",
          tint: "var(--down-tint)",
          deep: "var(--down-deep)",
        },
        warn: {
          DEFAULT: "var(--warn)",
          tint: "var(--warn-tint)",
          deep: "var(--warn-deep)",
        },
        bear: {
          DEFAULT: "var(--bear)",
          tint: "var(--bear-tint)",
          deep: "var(--bear-deep)",
        },
        regime: {
          bull: "var(--regime-bull)",
          chop: "var(--regime-chop)",
          bear: "var(--regime-bear)",
          crisis: "var(--regime-crisis)",
          neutral: "var(--regime-neutral)",
        },
      },
      fontFamily: {
        heading: ["Barlow Condensed", "system-ui", "sans-serif"],
        body: ["Barlow", "system-ui", "sans-serif"],
        sans: ["Barlow", "system-ui", "sans-serif"],
        mono: ["IBM Plex Mono", "monospace"],
      },
      spacing: {
        s1: "var(--space-1)",
        s2: "var(--space-2)",
        s3: "var(--space-3)",
        s4: "var(--space-4)",
        s6: "var(--space-6)",
        s8: "var(--space-8)",
      },
      borderRadius: {
        // Framed (blueprint) objects are square; sm/md/lg kept for the few
        // non-framed uses the tokens carry.
        none: "0",
        sm: "var(--radius-sm)",
        md: "var(--radius-md)",
        lg: "var(--radius-lg)",
      },
      boxShadow: {
        sm: "var(--shadow-sm)",
        md: "var(--shadow-md)",
        lg: "var(--shadow-lg)",
      },
    },
  },
  plugins: [],
};
