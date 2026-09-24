"use client";
import { useState } from "react";
import { api } from "@/lib/api";
export default function OfferResponse({ offer }: { offer: { id: string; status: string; expiry_date: string; offer_code: string; document_storage_path?: string } }) {
  const [message, setMessage] = useState(""); const [error, setError] = useState(""); const [busy, setBusy] = useState(false);
  async function respond(decision: "ACCEPTED" | "DECLINED") { if (!window.confirm(`Confirm offer ${decision.toLowerCase()}?`)) return; setBusy(true); setError(""); try { const result = await api<{ message: string }>(`/candidate/offers/${offer.id}/response`, { method: "PATCH", body: JSON.stringify({ decision, notes: "" }) }); setMessage(result.message); } catch (err) { setError(err instanceof Error ? err.message : "Offer response failed"); } finally { setBusy(false); } }
  async function download() { try { const result = await api<{ url: string }>(`/candidate/offers/${offer.id}/document`); window.open(result.url, "_blank", "noopener,noreferrer"); } catch (err) { setError(err instanceof Error ? err.message : "Offer letter unavailable"); } }
  return <div className="notice success"><b>Offer: {offer.status}</b><p>Offer code: {offer.offer_code} · Joining date: {offer.expiry_date}</p>{offer.document_storage_path && <button className="button small" onClick={download}>Review offer letter</button>}{offer.status === "APPROVED" || offer.status === "OFFERED" ? <><button className="button small" disabled={busy} onClick={() => respond("ACCEPTED")}>Accept offer</button><button className="button small ghost" disabled={busy} onClick={() => respond("DECLINED")}>Reject offer</button></> : null}{message && <p>{message}</p>}{error && <p role="alert">{error}</p>}</div>;
}
