/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        dark: {
          bg: {
            primary: 'rgb(var(--bg-primary) / <alpha-value>)',
            secondary: 'rgb(var(--bg-secondary) / <alpha-value>)',
            tertiary: 'rgb(var(--bg-tertiary) / <alpha-value>)',
          },
          text: {
            primary: 'rgb(var(--text-primary) / <alpha-value>)',
            secondary: 'rgb(var(--text-secondary) / <alpha-value>)',
          },
          border: 'rgb(var(--border) / <alpha-value>)',
          accent: {
            primary: 'rgb(var(--accent-primary) / <alpha-value>)',
            hover: 'rgb(var(--accent-hover) / <alpha-value>)',
          }
        }
      }
    },
  },
  plugins: [],
}
