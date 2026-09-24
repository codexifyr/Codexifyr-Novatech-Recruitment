"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api";

type Notification = { id: string; title: string; message: string; category?: string; action_url?: string; read_at?: string; created_at: string };
export default function NotificationsPage() {
  const [items, setItems] = useState<Notification[]>([]); const [error, setError] = useState("");
  async function load() { try { const result = await api<{ items: Notification[] }>("/operations/notifications"); setItems(result.items); } catch (err) { setError(err instanceof Error ? err.message : "Notifications could not load"); } }
  useEffect(() => { load(); }, []);
  async function markAll() { await api("/operations/notifications/read-all", { method: "PATCH" }); await load(); }
  async function markRead(item: Notification) { if (!item.read_at) { await api(`/operations/notifications/${item.id}/read`, { method: "PATCH" }); await load(); } }
  return <div className="resource-page"><div className="container section"><Link className="back" href="/dashboard">← Dashboard</Link><div className="table-head"><div><span className="eyebrow">Updates</span><h1>Notifications</h1></div><button className="button small" onClick={markAll}>Mark all as read</button></div>{error && <div className="notice error">{error}</div>}{items.map(item => <article className={item.read_at ? "notice" : "notice success"} key={item.id} onClick={() => markRead(item)}><b>{item.title}</b><p>{item.message}</p><small>{new Date(item.created_at).toLocaleString()} · {item.category || "General"}</small>{item.action_url && <Link className="arrow-link" href={item.action_url}>Open →</Link>}</article>)}{!items.length && !error && <div className="notice">No notifications.</div>}</div></div>;
}