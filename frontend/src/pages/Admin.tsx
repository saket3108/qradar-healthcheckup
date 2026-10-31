import { zodResolver } from "@hookform/resolvers/zod";
import { Loader2, UserPlus } from "lucide-react";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { Async, EmptyState, ErrorState, PageHeader, Section } from "@/components/common";
import { Badge } from "@/components/ui/badges";
import { Button } from "@/components/ui/button";
import { Input, Label, Select, Switch } from "@/components/ui/primitives";
import { useAppSelector } from "@/store/hooks";
import { can, ROLE_LABEL } from "@/store/auth";
import { useAudit, useUserMutations, useUsers } from "@/lib/queries";
import { errMsg, fmtDate } from "@/lib/utils";
import type { Role } from "@/types";

export const userSchema = z.object({
  email: z.string().min(1, "Email is required").email("Enter a valid email address"),
  full_name: z.string().trim().max(255).optional(),
  password: z.string().min(12, "Use at least 12 characters").max(72, "At most 72 characters"),
  role: z.enum(["administrator", "consultant", "manager", "read_only"]),
});
type UserForm = z.infer<typeof userSchema>;

function Users() {
  const me = useAppSelector((s) => s.auth.user);
  const q = useUsers();
  const { create, update } = useUserMutations();
  const [err, setErr] = useState<string | null>(null);
  const { register, handleSubmit, reset, formState: { errors, isSubmitting } } = useForm<UserForm>({ resolver: zodResolver(userSchema), defaultValues: { role: "consultant", email: "", password: "", full_name: "" } });
  const onSubmit = handleSubmit(async (v) => { setErr(null); try { await create.mutateAsync(v); reset(); } catch (e) { setErr(errMsg(e)); } });
  return (
    <div className="space-y-6">
      <Section title="Create user" description="Roles: Administrator (full access), IBM Consultant (upload, edit, export), Manager (view, export, audit), Read Only.">
        <form onSubmit={onSubmit} noValidate aria-label="Create user" className="grid gap-4 md:grid-cols-2 xl:grid-cols-5">
          <div className="space-y-1.5"><Label htmlFor="u-email">Email</Label><Input id="u-email" type="email" autoComplete="off" aria-invalid={!!errors.email} {...register("email")} />{errors.email && <p role="alert" className="text-xs text-sev-critical">{errors.email.message}</p>}</div>
          <div className="space-y-1.5"><Label htmlFor="u-name">Full name</Label><Input id="u-name" {...register("full_name")} /></div>
          <div className="space-y-1.5"><Label htmlFor="u-pass">Temporary password</Label><Input id="u-pass" type="password" autoComplete="new-password" aria-invalid={!!errors.password} {...register("password")} />{errors.password && <p role="alert" className="text-xs text-sev-critical">{errors.password.message}</p>}</div>
          <div className="space-y-1.5"><Label htmlFor="u-role">Role</Label><Select id="u-role" className="w-full" {...register("role")}>{(Object.keys(ROLE_LABEL) as Role[]).map((r) => <option key={r} value={r}>{ROLE_LABEL[r]}</option>)}</Select></div>
          <div className="flex items-end"><Button type="submit" disabled={isSubmitting} className="w-full">{isSubmitting ? <Loader2 className="animate-spin" /> : <UserPlus />}Create user</Button></div>
        </form>
        {err && <p role="alert" className="mt-3 text-sm text-sev-critical">{err}</p>}
      </Section>
      <Section title="Users" bodyClassName="overflow-x-auto p-0">
        <Async q={q}>{(users) => (
          <table className="w-full min-w-[720px] text-sm"><thead><tr className="border-b text-left [&>th]:px-4 [&>th]:py-2.5"><th className="label-caps">User</th><th className="label-caps">Role</th><th className="label-caps">Last login</th><th className="label-caps">Active</th></tr></thead>
            <tbody>{users.map((u) => (
              <tr key={u.id} className="border-b last:border-0 [&>td]:px-4 [&>td]:py-2.5"><td><div className="font-medium">{u.full_name || u.email}</div><div className="text-xs text-muted-foreground">{u.email}</div></td>
                <td><Select aria-label={`Role for ${u.email}`} value={u.role} disabled={u.id === me?.id || update.isPending} onChange={(e) => update.mutate({ id: u.id, role: e.target.value })}>{(Object.keys(ROLE_LABEL) as Role[]).map((r) => <option key={r} value={r}>{ROLE_LABEL[r]}</option>)}</Select></td>
                <td className="text-xs text-muted-foreground">{fmtDate(u.last_login)}</td>
                <td><Switch aria-label={`Active ${u.email}`} checked={u.is_active} onCheckedChange={(v) => update.mutate({ id: u.id, is_active: v })} /></td></tr>))}</tbody></table>
        )}</Async>
        {update.error && <div className="p-4"><ErrorState error={update.error} /></div>}
      </Section>
    </div>
  );
}

const ACTIONS = ["", "login", "login_failed", "upload", "report_created", "report_modified", "comment_updated", "export_generated", "finding_updated", "assessment_reprocessed", "assessment_deleted", "user_created", "user_updated", "assistant_query"];

function Audit() {
  const [action, setAction] = useState("");
  const q = useAudit(undefined, action || undefined);
  return (
    <Section title="Audit log" description="Report creation, modification, comment updates and export generation are tracked here."
      actions={<Select aria-label="Filter by action" value={action} onChange={(e) => setAction(e.target.value)}>{ACTIONS.map((a) => <option key={a} value={a}>{a || "All actions"}</option>)}</Select>} bodyClassName="overflow-x-auto p-0">
      <Async q={q}>{(rows) => rows.length === 0 ? <div className="p-4"><EmptyState title="No audit events" /></div> : (
        <table className="w-full min-w-[820px] text-sm"><thead><tr className="border-b text-left [&>th]:px-4 [&>th]:py-2.5"><th className="label-caps">Time</th><th className="label-caps">User</th><th className="label-caps">Action</th><th className="label-caps">Target</th><th className="label-caps">IP</th></tr></thead>
          <tbody>{rows.map((r) => <tr key={r.id} className="border-b last:border-0 [&>td]:px-4 [&>td]:py-2 hover:bg-accent/40"><td className="whitespace-nowrap text-xs text-muted-foreground">{fmtDate(r.ts)}</td><td>{r.user ?? "—"}</td><td><Badge tone={r.action.includes("failed") || r.action.includes("deleted") ? "high" : "primary"}>{r.action}</Badge></td><td className="max-w-[300px] truncate text-xs text-muted-foreground" title={r.target ?? ""}>{r.target ?? r.assessment_id ?? "—"}</td><td className="font-mono text-xs">{r.ip ?? "—"}</td></tr>)}</tbody></table>
      )}</Async>
    </Section>
  );
}

export default function Admin() {
  const role = useAppSelector((s) => s.auth.user?.role);
  return (
    <div>
      <PageHeader title={can(role, "manage_users") ? "Administration" : "Audit"} description={can(role, "manage_users") ? "User management and platform audit trail." : "Platform audit trail."} />
      <div className="space-y-6">{can(role, "manage_users") && <Users />}<Audit /></div>
    </div>
  );
}
