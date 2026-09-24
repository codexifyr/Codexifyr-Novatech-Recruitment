"use client";
import { FormEvent, useEffect, useState } from "react";
import { api } from "@/lib/api";
export default function AvailabilityEditor() {
  const [profileId, setProfileId] = useState(""); const [message, setMessage] = useState("");
  useEffect(() => { api<{ user: { id: string } }>("/auth/me").then(result => setProfileId(result.user.id)).catch(() => undefined); }, []);
  async function save(event: FormEvent<HTMLFormElement>) { event.preventDefault(); const data = new FormData(event.currentTarget); try { await api(`/admin/interviewers/${profileId}/availability`, { method: "POST", body: JSON.stringify({ starts_at: new Date(String(data.get("starts_at"))).toISOString(), ends_at: new Date(String(data.get("ends_at"))).toISOString(), unavailable: data.get("unavailable") === "on" }) }); setMessage("Availability saved"); event.currentTarget.reset(); } catch (err) { setMessage(err instanceof Error ? err.message : "Availability could not save"); } }
  if (!profileId) return null;
  return <form className="form-card" onSubmit={save}><h2>Availability</h2><label>Starts<input name="starts_at" type="datetime-local" required /></label><label>Ends<input name="ends_at" type="datetime-local" required /></label><label className="check"><input name="unavailable" type="checkbox" />Mark unavailable</label><button className="button">Save availability</button>{message && <p role="status">{message}</p>}</form>;
}
