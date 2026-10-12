/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: "#0f1c2e",
        mist: "#e8eef5",
        sea: "#1a6b8a",
        coral: "#c45c26",
        sage: "#3d7a5c",
      },
      fontFamily: {
        display: ["\"Fraunces\"", "Georgia", "serif"],
        sans: ["\"DM Sans\"", "Segoe UI", "sans-serif"],
      },
    },
  },
  plugins: [],
};
