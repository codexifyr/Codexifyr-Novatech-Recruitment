"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";

type Persona = { id: string; full_name: string; role: string; department?: string; job_title?: string };

export default function StaffSelect() {
  const router = useRouter();
  const [items, setItems] = useState<Persona[]>([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState("");
  useEffect(() => { api<{items: Persona[]}>("/auth/staff-personas").then(result => setItems(result.items)).catch(reason => setError(reason.message)); }, []);
  async function select(profile: Persona) {
    setBusy(profile.id); setError("");
    try {
      await api("/auth/staff-personas/select", { method: "POST", body: JSON.stringify({ profile_id: profile.id }) });
      window.dispatchEvent(new Event("novatech-auth-changed"));
      router.push("/dashboard"); router.refresh();
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Profile could not be selected"); }
    finally { setBusy(""); }
  }
  return <div className="resource-page"><div className="container section"><span className="eyebrow">Shared staff workspace</span><h1>Choose your staff profile</h1><p className="muted">Actions and notifications are recorded under the selected role.</p>{error && <div className="notice error">{error}</div>}<div className="metric-cards">{items.map(item => <article key={item.id}><span>{item.department || "NovaTech"}</span><h2>{item.full_name}</h2><p>{item.job_title || item.role}</p><button className="button full" disabled={busy === item.id} onClick={() => select(item)}>{busy === item.id ? "Opening…" : "Open dashboard"}</button></article>)}</div>{!items.length && !error && <div className="notice">Loading staff profiles…</div>}</div></div>;
}
