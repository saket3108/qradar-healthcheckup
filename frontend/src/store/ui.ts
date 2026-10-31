import { createSlice } from "@reduxjs/toolkit";

export type Theme = "dark" | "light";
const KEY = "qhc.theme";
export function initialTheme(): Theme {
  const v = typeof localStorage !== "undefined" ? localStorage.getItem(KEY) : null;
  return v === "light" ? "light" : "dark";            // dark by default
}
export function applyTheme(t: Theme) {
  document.documentElement.classList.toggle("dark", t === "dark");
  try { localStorage.setItem(KEY, t); } catch { /* ignore */ }
}

const slice = createSlice({
  name: "ui",
  initialState: { theme: initialTheme(), sidebarCollapsed: false },
  reducers: {
    setTheme(s, a: { payload: Theme }) { s.theme = a.payload; },
    toggleTheme(s) { s.theme = s.theme === "dark" ? "light" : "dark"; },
    toggleSidebar(s) { s.sidebarCollapsed = !s.sidebarCollapsed; },
  },
});
export const { setTheme, toggleTheme, toggleSidebar } = slice.actions;
export default slice.reducer;
