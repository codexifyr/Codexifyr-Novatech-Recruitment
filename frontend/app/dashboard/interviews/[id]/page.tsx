"use client";

import { FormEvent, useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { api } from "@/lib/api";

type Account = { id: string; role: string; full_name: string };

export default function InterviewWorkspace() {
  const { id } = useParams<{ id: string }>();
  const [item, setItem] = useState<any>(null);
  const [me, setMe] = useState<Account | null>(null);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState("");

  async function load() {
    try {
      const [result, account] = await Promise.all([
        api<{ item: any }>(`/admin/interviews/${id}/workspace`),
        api<{ user: Account }>("/auth/me"),
      ]);
      setItem(result.item);
      setMe(account.user);
      setError("");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Interview could not load");
    }
  }

  useEffect(() => { load(); }, [id]);

  async function assignmentResponse(response: "ACCEPTED" | "DECLINED") {
    const reason = response === "DECLINED" ? window.prompt("Why can you not take this interview?") || "Unavailable" : "";
    setBusy(response);
    try {
      const result = await api<{ message: string }>(`/admin/interviews/${id}/response`, {
        method: "PATCH",
        body: JSON.stringify({ response, reason }),
      });
      setMessage(result.message);
      await load();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Response could not be saved");
    } finally {
      setBusy("");
    }
  }

  async function schedule(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    const start = new Date(String(data.get("start")));
    const duration = Number(data.get("duration") || item.duration_minutes || 60);
    const end = new Date(start.getTime() + duration * 60000);
    setBusy("schedule");
    setError("");
    try {
      const result = await api<{ message: string }>(`/admin/interviews/${id}/schedule`, {
        method: "POST",
        body: JSON.stringify({
          scheduled_start: start.toISOString(),
          scheduled_end: end.toISOString(),
          timezone: data.get("timezone"),
          send_email: true,
        }),
      });
      setMessage(result.message);
      await load();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Schedule could not be created");
    } finally {
      setBusy("");
    }
  }

  async function decideReschedule(form: HTMLFormElement, decision: "ACCEPTED" | "REJECTED") {
    const data = new FormData(form);
    setBusy(`reschedule-${decision}`);
    try {
      const result = await api<{ message: string }>(`/admin/interviews/${id}/reschedule-decision`, {
        method: "PATCH",
        body: JSON.stringify({ decision, reason: data.get("reason") }),
      });
      setMessage(result.message);
      await load();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Reschedule decision could not be saved");
    } finally {
      setBusy("");
    }
  }

  async function score(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    setBusy("score");
    setError("");
    try {
      const fields = ["technical_score", "communication_score", "problem_solving_score", "experience_score", "team_fit_score", "overall_score"];
      const payload = Object.fromEntries(fields.map(key => [key, Number(data.get(key))]));
      const result = await api<{ message: string }>(`/admin/interviews/${id}/scorecard`, {
        method: "POST",
        body: JSON.stringify({ ...payload, recommendation: data.get("recommendation"), comments: data.get("comments") }),
      });
      setMessage(result.message);
      await load();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Scorecard could not be saved");
    } finally {
      setBusy("");
    }
  }

  if (!item) return <div className="container section"><div className="notice">Loading interview workspace…</div>{error && <div className="notice error">{error}</div>}</div>;

  const application = item.applications || {};
  const job = application.job_positions || {};
  const review = application.ai_review || {};
  const assignedToMe = me?.id === item.interviewer_id;
  const approved = item.assignment_status === "APPROVED";
  const accepted = item.interviewer_response === "ACCEPTED";
  const canConduct = assignedToMe && approved && accepted;
  const canDecideReschedule = !!me && (["admin", "hr", "hiring_manager"].includes(me.role) || assignedToMe);
  const pendingReschedule = item.reschedule_requested_at && !item.reschedule_decision_status;

  return (
    <div className="resource-page">
      <div className="container section">
        <Link className="back" href="/dashboard/interviews">← Interviews</Link>
        <span className="eyebrow">{item.interview_code}</span>
        <h1>{application.name_at_application}</h1>
        {message && <div className="notice success">{message}</div>}
        {error && <div className="notice error">{error}</div>}

        <div className="metric-cards">
          <article><span>Position</span><b>{job.title || "—"}</b></article>
          <article><span>CV score</span><b>{application.final_score ?? "—"}</b></article>
          <article><span>Status</span><b>{String(item.status).replaceAll("_", " ")}</b></article>
        </div>

        {assignedToMe && approved && !item.interviewer_response && (
          <section className="form-card assignment-response">
            <div><h2>Assignment approval received</h2><p>Review the CV and accept this interview before selecting the schedule.</p></div>
            <div className="button-row"><button className="button" disabled={!!busy} onClick={() => assignmentResponse("ACCEPTED")}>Accept assignment</button><button className="button danger" disabled={!!busy} onClick={() => assignmentResponse("DECLINED")}>Decline & reassign</button></div>
          </section>
        )}

        {pendingReschedule && canDecideReschedule && (
          <form className="form-card reschedule-card" onSubmit={event => { event.preventDefault(); decideReschedule(event.currentTarget, "ACCEPTED"); }}>
            <span className="eyebrow">Candidate request</span>
            <h2>Review requested interview time</h2>
            <p><b>Preferred time:</b> {new Date(item.reschedule_requested_start).toLocaleString()}</p>
            {item.candidate_response_note && <p><b>Candidate note:</b> {item.candidate_response_note}</p>}
            <label>Decision note<textarea name="reason" rows={3} placeholder="Optional when accepting; required context is recommended when rejecting." /></label>
            <div className="button-row"><button className="button" disabled={!!busy}>Accept and update Google Meet</button><button type="button" className="button danger" disabled={!!busy} onClick={event => event.currentTarget.form && decideReschedule(event.currentTarget.form, "REJECTED")}>Reject; keep original schedule</button></div>
          </form>
        )}

        <div className="detail-grid">
          <section className="table-card">
            <h2>Candidate review</h2>
            <dl className="profile-grid">
              <div><dt>Email</dt><dd>{application.email_at_application}</dd></div>
              <div><dt>Phone</dt><dd>{application.phone_at_application}</dd></div>
              <div><dt>Department</dt><dd>{job.department || "—"}</dd></div>
              <div><dt>Experience</dt><dd>{review.cv_experience_years ?? application.experience_years ?? "—"} years</dd></div>
              <div><dt>Verified CV skills</dt><dd>{review.verified_skills?.join(", ") || "—"}</dd></div>
              <div><dt>CV security</dt><dd><span className="status">{application.cv_security_status || "NOT SCANNED"}</span></dd></div>
            </dl>
            {application.cv_download && <a className="button" href={application.cv_download} target="_blank" rel="noreferrer">View / download CV</a>}
            <h2>Evidence-based AI review</h2>
            <p>{review.candidate_summary || "No review summary is available."}</p>
            <p><b>Recommendation:</b> {review.ai_recommendation || "—"}</p>
            {review.score_breakdown?.length > 0 && <div className="table-scroll"><table><thead><tr><th>Criterion</th><th>Score</th><th>Evidence</th></tr></thead><tbody>{review.score_breakdown.map((row: any) => <tr key={row.criterion}><td>{row.criterion}</td><td>{row.points}/{row.maximum}</td><td>{row.evidence}</td></tr>)}</tbody></table></div>}
          </section>

          <aside>
            {canConduct ? (
              <>
                <form className="form-card" onSubmit={schedule}>
                  <h2>{item.google_event_id ? "Update interview schedule" : "Schedule Google Meet"}</h2>
                  <p className="muted">The system checks conflicts, creates or updates the same Calendar event, then sends structured invitations.</p>
                  <label>Date and time<input name="start" type="datetime-local" required /></label>
                  <label>Duration<select name="duration" defaultValue={String(item.duration_minutes || 60)}><option value="30">30 minutes</option><option value="45">45 minutes</option><option value="60">60 minutes</option><option value="90">90 minutes</option></select></label>
                  <label>Timezone<select name="timezone" defaultValue={item.schedule_timezone || "Asia/Karachi"}><option value="Asia/Karachi">Pakistan Standard Time</option><option value="UTC">UTC</option><option value="Asia/Dubai">Gulf Standard Time</option><option value="Europe/London">London</option><option value="America/New_York">New York</option></select></label>
                  <button className="button full" disabled={!!busy}>{busy === "schedule" ? "Saving…" : "Save schedule and send invitations"}</button>
                </form>
                <form className="form-card" onSubmit={score}>
                  <h2>Interview scorecard</h2>
                  {[["technical_score", "Technical"], ["communication_score", "Communication"], ["problem_solving_score", "Problem solving"], ["experience_score", "Experience"], ["team_fit_score", "Team fit"]].map(([name, label]) => <label key={name}>{label}<input name={name} type="number" min="1" max="10" required /></label>)}
                  <label>Overall<input name="overall_score" type="number" min="1" max="10" step="0.1" required /></label>
                  <label>Recommendation<select name="recommendation"><option value="STRONG_HIRE">Strong hire</option><option value="HIRE">Hire</option><option value="REVIEW">Review</option><option value="NO_HIRE">No hire</option><option value="STRONG_NO_HIRE">Strong no hire</option></select></label>
                  <label>Comments<textarea name="comments" rows={4} /></label>
                  <button className="button full" disabled={!!busy}>Submit scorecard</button>
                </form>
              </>
            ) : (
              <div className="notice">{assignedToMe && approved ? "Accept this assignment to schedule the interview and submit its scorecard." : "Only the approved assigned interviewer can schedule this meeting or submit its scorecard."}</div>
            )}
            {item.meeting_url && (
              <section className="form-card">
                <h2>Meeting details</h2>
                <p><b>Start:</b><br />{new Date(item.scheduled_start).toLocaleString()}</p>
                <p><b>End:</b><br />{new Date(item.scheduled_end).toLocaleString()}</p>
                <p><b>Candidate response:</b><br />{String(item.status).replaceAll("_", " ")}</p>
                <p><b>Meeting code:</b><br />{item.meeting_code || "Contained in link"}</p>
                <a className="button full" href={item.meeting_url} target="_blank" rel="noreferrer">Join Google Meet</a>
                {item.google_event_url && <a className="text-link" href={item.google_event_url} target="_blank" rel="noreferrer">Open Google Calendar event</a>}
              </section>
            )}
          </aside>
        </div>
      </div>
    </div>
  );
}
