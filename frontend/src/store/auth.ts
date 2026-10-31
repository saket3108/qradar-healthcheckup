import { createSlice, type PayloadAction } from "@reduxjs/toolkit";
import type { Role, User } from "@/types";

const KEY = "qhc.auth";
interface AuthState { token: string | null; user: User | null }

function load(): AuthState {
  try {
    const raw = localStorage.getItem(KEY);
    if (raw) return JSON.parse(raw) as AuthState;
  } catch { /* ignore */ }
  return { token: null, user: null };
}

const slice = createSlice({
  name: "auth",
  initialState: load(),
  reducers: {
    loggedIn(state, a: PayloadAction<{ token: string; user: User }>) { state.token = a.payload.token; state.user = a.payload.user; },
    userUpdated(state, a: PayloadAction<User>) { state.user = a.payload; },
    logout(state) { state.token = null; state.user = null; },
  },
});
export const { loggedIn, userUpdated, logout } = slice.actions;
export default slice.reducer;
export const AUTH_KEY = KEY;

export type Perm = "view" | "upload" | "edit" | "export" | "delete" | "audit" | "manage_users";
const PERMS: Record<Role, Perm[]> = {
  administrator: ["view", "upload", "edit", "export", "delete", "audit", "manage_users"],
  consultant: ["view", "upload", "edit", "export"],
  manager: ["view", "export", "audit"],
  read_only: ["view"],
};
export const can = (role: Role | undefined | null, perm: Perm) => !!role && PERMS[role]?.includes(perm);
export const ROLE_LABEL: Record<Role, string> = { administrator: "Administrator", consultant: "IBM Consultant", manager: "Manager", read_only: "Read Only" };
