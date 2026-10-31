import { Activity, LogOut, Moon, Shield, ShieldCheck, Sun, Users } from "lucide-react";
import { Link, NavLink, Outlet } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badges";
import { useAppDispatch, useAppSelector } from "@/store/hooks";
import { can, logout, ROLE_LABEL } from "@/store/auth";
import { toggleTheme } from "@/store/ui";
import { cn } from "@/lib/utils";

export default function AppShell() {
  const dispatch = useAppDispatch();
  const qc = useQueryClient();
  const user = useAppSelector((s) => s.auth.user);
  const theme = useAppSelector((s) => s.ui.theme);
  const initials = (user?.full_name || user?.email || "?").split(/[\s@.]/).filter(Boolean).slice(0, 2).map((x) => x[0]!.toUpperCase()).join("");

  return (
    <div className="relative min-h-screen">
      <div className="aurora pointer-events-none absolute inset-x-0 top-0 h-[420px]" aria-hidden />
      <header className="glass sticky top-0 z-40 border-x-0 border-t-0">
        <div className="mx-auto flex h-14 max-w-[1600px] items-center gap-4 px-4 lg:px-6">
          <Link to="/" className="flex items-center gap-2.5 font-semibold tracking-tight">
            <span className="grid size-8 place-items-center rounded-lg bg-primary text-primary-foreground shadow-[0_0_20px_-4px_hsl(var(--primary))]"><Activity className="size-4.5" /></span>
            <span className="hidden sm:inline">QRadar Health Checkup</span>
          </Link>
          <nav className="ml-4 flex items-center gap-1 text-sm" aria-label="Primary">
            <NavLink to="/" end className={({ isActive }) => cn("flex items-center gap-1.5 rounded-md px-3 py-1.5 text-muted-foreground hover:text-foreground", isActive && "bg-accent text-foreground")}><ShieldCheck className="size-4" />Assessments</NavLink>
            {can(user?.role, "audit") && (
              <NavLink to="/admin" className={({ isActive }) => cn("flex items-center gap-1.5 rounded-md px-3 py-1.5 text-muted-foreground hover:text-foreground", isActive && "bg-accent text-foreground")}>
                {can(user?.role, "manage_users") ? <Users className="size-4" /> : <Shield className="size-4" />}{can(user?.role, "manage_users") ? "Admin" : "Audit"}
              </NavLink>
            )}
          </nav>
          <div className="ml-auto flex items-center gap-2">
            <Button variant="ghost" size="icon" aria-label={`Switch to ${theme === "dark" ? "light" : "dark"} mode`} onClick={() => dispatch(toggleTheme())}>
              {theme === "dark" ? <Sun /> : <Moon />}
            </Button>
            <div className="hidden items-center gap-2 border-l pl-3 sm:flex">
              <div className="grid size-8 place-items-center rounded-full bg-accent text-xs font-semibold">{initials}</div>
              <div className="leading-tight">
                <div className="max-w-[160px] truncate text-xs font-medium">{user?.full_name || user?.email}</div>
                <Badge tone="primary" className="mt-0.5 !py-0 text-[10px]">{user ? ROLE_LABEL[user.role] : ""}</Badge>
              </div>
            </div>
            <Button variant="ghost" size="icon" aria-label="Sign out" onClick={() => { dispatch(logout()); qc.clear(); }}><LogOut /></Button>
          </div>
        </div>
      </header>
      <main className="relative mx-auto max-w-[1600px] px-4 py-6 lg:px-6"><Outlet /></main>
    </div>
  );
}
