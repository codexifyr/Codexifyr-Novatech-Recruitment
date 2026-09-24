"use client";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
const permissions = ["users.manage", "jobs.manage", "applications.view", "applications.manage", "interviews.assign", "interviews.conduct", "offers.manage", "offers.approve", "employees.manage", "reports.view", "audit.view", "workflows.manage"];
export default function UserAccessEditor({ profileId }: { profileId: string }) {
  const [open, setOpen] = useState(false); const [roles, setRoles] = useState<string[]>([]); const [allowed, setAllowed] = useState<string[]>([]); const [denied, setDenied] = useState<string[]>([]); const [message, setMessage] = useState("");
  async function load() { const result = await api<{ roles: string[]; overrides: { permission_key: string; allowed: boolean }[] }>(`/admin/users/${profileId}/access`); setRoles(result.roles); setAllowed(result.overrides.filter(item => item.allowed).map(item => item.permission_key)); setDenied(result.overrides.filter(item => !item.allowed).map(item => item.permission_key)); }
  useEffect(() => { if (open) load().catch(() => setMessage("Access could not load")); }, [open]);
  async function save() { try { await api(`/admin/users/${profileId}/access`, { method: "PUT", body: JSON.stringify({ roles, allowed_permissions: allowed, denied_permissions: denied }) }); setMessage("Access saved"); } catch (err) { setMessage(err instanceof Error ? err.message : "Access could not save"); } }
  return <><button className="button small ghost" onClick={() => setOpen(!open)}>{open ? "Close access" : "Overrides"}</button>{open && <div className="notice"><b>Permission overrides</b>{permissions.map(permission => <label className="check" key={permission}><input type="checkbox" checked={allowed.includes(permission)} onChange={event => { setAllowed(current => event.target.checked ? [...current, permission] : current.filter(item => item !== permission)); setDenied(current => current.filter(item => item !== permission)); }} />Allow {permission}</label>)}<button className="button small" onClick={save}>Save overrides</button>{message && <p role="status">{message}</p>}</div>}</>;
}
