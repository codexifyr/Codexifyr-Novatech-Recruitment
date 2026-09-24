"use client";

import { FormEvent, useEffect, useState } from "react";
import { api } from "@/lib/api";

type InterviewDetails = {
  interview_code: string;
  status: string;
  scheduled_start?: string;
  scheduled_end?: string;
  timezone?: string;
  candidate_name?: string;
  position?: string;
};

export default function ActionForm({ type }: { type: "interview" | "offer" }) {
  const [reference, setReference] = useState("");
  const [responseToken, setResponseToken] = useState("");
  const [action, setAction] = useState("CONFIRMED");
  const [details, setDetails] = useState<InterviewDetails | null>(null);
  const [loading, setLoading] = useState(type === "interview");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    if (type === "offer") {
      const params = new URLSearchParams(window.location.search);
      setReference(params.get("offer_id") || "");
      setResponseToken(params.get("token") || "");
      setLoading(false);
      return;
    }
    const params = new URLSearchParams(window.location.search);
    const token = params.get("token") || "";
    const requestedAction = params.get("action");
    setReference(token);
    if (requestedAction === "RESCHEDULE") setAction("RESCHEDULE");
    if (!token) {
      setError("Open the secure response link from your interview email.");
      setLoading(false);
      return;
    }
    api<{ item: InterviewDetails }>(`/interviews/respond?token=${encodeURIComponent(token)}`)
      .then(result => {
        setDetails(result.item);
        setError("");
      })
      .catch(reason => setError(reason instanceof Error ? reason.message : "Interview details could not load"))
      .finally(() => setLoading(false));
  }, [type]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError("");
    setMessage("");
    const data = new FormData(event.currentTarget);
    try {
      if (type === "offer") {
        const result = await api<{ message: string }>("/offers/respond", {
          method: "POST",
          body: JSON.stringify({
            offer_id: data.get("reference"),
            response_token: responseToken,
            response: data.get("action"),
            notes: data.get("notes"),
          }),
        });
        setMessage(result.message);
        return;
      }

      const requested = String(data.get("requested_start") || "");
      const payload = {
        confirmation_token: reference,
        action,
        requested_start: action === "RESCHEDULE" && requested
          ? new Date(requested).toISOString()
          : undefined,
        note: String(data.get("notes") || ""),
      };
      const path = action === "RESCHEDULE" ? "/interviews/reschedule" : "/interviews/confirm";
      const result = await api<{ message: string }>(path, {
        method: "POST",
        body: JSON.stringify(payload),
      });
      setMessage(result.message);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Request failed");
    } finally {
      setBusy(false);
    }
  }

  if (loading) return <div className="notice">Loading your secure interview invitation…</div>;

  return (
    <form className="form-card" onSubmit={submit}>
      {type === "interview" ? (
        <>
          {details && (
            <section className="response-summary">
              <span className="eyebrow">{details.interview_code}</span>
              <h2>{details.position || "Interview"}</h2>
              <p><b>Candidate:</b> {details.candidate_name || "Candidate"}</p>
              <p><b>Current time:</b> {details.scheduled_start ? new Date(details.scheduled_start).toLocaleString() : "Not scheduled"}</p>
              <p><b>Status:</b> <span className="status">{details.status.replaceAll("_", " ")}</span></p>
            </section>
          )}
          <label>
            Your response
            <select value={action} onChange={event => setAction(event.target.value)}>
              <option value="CONFIRMED">Confirm this interview time</option>
              <option value="RESCHEDULE">Request another time</option>
            </select>
          </label>
          {action === "RESCHEDULE" && (
            <label>
              Preferred new date and time
              <input name="requested_start" type="datetime-local" required />
              <small>HR, the hiring manager or your assigned interviewer will approve or reject this request.</small>
            </label>
          )}
          <label>
            Note (optional)
            <textarea name="notes" rows={4} maxLength={1000} placeholder="Share availability or a reason for the request." />
          </label>
        </>
      ) : (
        <>
          <label>Offer ID<input name="reference" value={reference} onChange={event => setReference(event.target.value)} readOnly={!!responseToken} required /></label>
          {!responseToken && <div className="notice error">Open the secure response link from your offer email.</div>}
          <label>
            Response
            <select name="action">
              <option value="ACCEPTED">Accept offer</option>
              <option value="DECLINED">Decline offer</option>
            </select>
          </label>
          <label>Notes (optional)<textarea name="notes" rows={4} /></label>
        </>
      )}
      {message && <div className="notice success">{message}</div>}
      {error && <div className="notice error">{error}</div>}
      <button className="button full" disabled={busy || !reference || (type === "offer" && !responseToken)}>
        {busy ? "Sending…" : action === "RESCHEDULE" ? "Send reschedule request" : "Submit response"}
      </button>
    </form>
  );
}
