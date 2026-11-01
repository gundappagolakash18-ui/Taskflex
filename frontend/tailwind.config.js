/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        primary: {
          50: "#eef4ff",
          100: "#dbe6fe",
          200: "#bfd3fe",
          300: "#93b4fd",
          400: "#6090fa",
          500: "#3b6cf6",
          600: "#2551eb",
          700: "#1d3ed8",
          800: "#1e35af",
          900: "#1e318a",
          950: "#172054",
        },
        accent: {
          50: "#fff8eb",
          100: "#ffeec6",
          200: "#ffda88",
          300: "#ffc14a",
          400: "#ffa020",
          500: "#f97f07",
          600: "#ea6002",
          700: "#c24704",
          800: "#9a380b",
          900: "#7c2f0c",
          950: "#451603",
        },
      },
      fontFamily: {
        sans: [
          "Inter",
          "ui-sans-serif",
          "system-ui",
          "-apple-system",
          "Segoe UI",
          "Roboto",
          "Helvetica Neue",
          "Arial",
          "sans-serif",
        ],
      },
      animation: {
        "pulse-soft": "pulse 2s cubic-bezier(0.4, 0, 0.6, 1) infinite",
        shimmer: "shimmer 1.8s linear infinite",
        "slide-up": "slideUp 0.25s ease-out",
      },
      keyframes: {
        shimmer: {
          "0%": { backgroundPosition: "-600px 0" },
          "100%": { backgroundPosition: "600px 0" },
        },
        slideUp: {
          "0%": { opacity: "0", transform: "translateY(8px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
      },
    },
  },
  plugins: [],
};
