import { configureStore } from "@reduxjs/toolkit";
import auth, { AUTH_KEY } from "./auth";
import ui, { applyTheme } from "./ui";

export const store = configureStore({ reducer: { auth, ui } });
export type RootState = ReturnType<typeof store.getState>;
export type AppDispatch = typeof store.dispatch;

let lastTheme = store.getState().ui.theme;
applyTheme(lastTheme);
store.subscribe(() => {
  const s = store.getState();
  try { localStorage.setItem(AUTH_KEY, JSON.stringify(s.auth)); } catch { /* ignore */ }
  if (s.ui.theme !== lastTheme) { lastTheme = s.ui.theme; applyTheme(lastTheme); }
});
