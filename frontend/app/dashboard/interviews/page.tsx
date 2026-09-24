"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api";
import AvailabilityEditor from "@/components/AvailabilityEditor";

type User = { id: string; role: string; full_name: string; department?: string };
type Interviewer = { id: string; full_name: string; role: string; department?: string; job_title?: string };
type Interview = {
  id: string;
  interview_code: string;
  status: string;
  assignment_status: string;
  interview_type: string;
  round_number: number;
  scheduled_start?: string;
  interviewer_id?: string;
  reschedule_requested_at?: string;
  reschedule_requested_start?: string;
  reschedule_decision_status?: string;
  applications?: {
    name_at_application: string;
    job_positions?: { title: string; department?: string };
  };
  user_profiles?: Interviewer;
};

const assignmentRoles = new Set(["admin", "hiring_manager", "hr"]);

export default function InterviewsPage() {
  const [me, setMe] = useState<User | null>(null);
  const [items, setItems] = useState<Interview[]>([]);
  const [people, setPeople] = useState<Interviewer[]>([]);
  const [selected, setSelected] = useState<Interview | null>(null);
  const [view, setView] = useState<"UPCOMING" | "PAST" | "ALL">("UPCOMING");
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  async function load() {
    try {
      const [account, interviews] = await Promise.all([
        api<{ user: User }>("/auth/me"),
        api<{ items: Interview[] }>("/admin/interviews"),
      ]);
      setMe(account.user);
      setItems(interviews.items);
      setError("");
      if (assignmentRoles.has(account.user.role)) {
        const result = await api<{ items: Interviewer[] }>("/admin/interviewers");
        setPeople(result.items);
      } else {
        setPeople([]);
      }
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Interviews could not load");
    }
  }

  useEffect(() => { load(); }, []);

  const eligiblePeople = useMemo(() => {
    if (!selected) return [];
    const department = selected.applications?.job_positions?.department?.trim().toLowerCase();
    return people.filter(person => {
      if (person.role === "hr") return true;
      return ["interviewer", "hiring_manager"].includes(person.role)
        && person.department?.trim().toLowerCase() === department;
    });
  }, [people, selected]);

  async function assign(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selected) return;
    const data = new FormData(event.currentTarget);
    try {
      const result = await api<{ message: string }>(`/admin/interviews/${selected.id}/assignment`, {
        method: "PATCH",
        body: JSON.stringify({
          interviewer_id: data.get("interviewer_id"),
          interview_type: data.get("interview_type"),
          round_number: Number(data.get("round_number")),
          duration_minutes: Number(data.get("duration_minutes")),
          assignment_role: "LEAD",
          approve: true,
        }),
      });
      setMessage(result.message);
      setSelected(null);
      await load();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Assignment failed");
    }
  }

  const interviewerView = me?.role === "interviewer";
  const canAssign = !!me && assignmentRoles.has(me.role);
  const canManageAvailability = !!me && ["interviewer", "hiring_manager", "hr"].includes(me.role);
  const visibleItems = useMemo(() => items.filter(item => {
    const past = ["COMPLETED", "CANCELLED", "NO_SHOW"].includes(item.status)
      || (!!item.scheduled_start && new Date(item.scheduled_start).getTime() < Date.now());
    return view === "ALL" || (view === "PAST" ? past : !past);
  }), [items, view]);

  return (
    <div className="resource-page">
      <div className="container section">
        <Link className="back" href="/dashboard">← Dashboard</Link>
        <span className="eyebrow">Interview operations</span>
        <h1>{interviewerView ? "My assigned interviews" : "Interviews & assignments"}</h1>
        <p className="lead small">
          {interviewerView
            ? "Review the candidate CV, accept your assignment, choose the exact schedule and conduct the interview."
            : "Automatic suggestions require approval. Assignment follows job department first, with HR as fallback; administrators are never interviewers."}
        </p>
        {message && <div className="notice success">{message}</div>}
        {error && <div className="notice error">{error}</div>}
        {canManageAvailability && <AvailabilityEditor />}
        <div className="button-row">
          {(["UPCOMING", "PAST", "ALL"] as const).map(value => <button key={value} className={`button small ${view === value ? "" : "ghost"}`} onClick={() => setView(value)}>{value === "PAST" ? "Past interviews" : value === "UPCOMING" ? "Upcoming" : "All"}</button>)}
        </div>
        <section className="table-card">
          <div className="table-scroll">
            <table>
              <thead><tr><th>Candidate</th><th>Interview</th><th>Schedule</th><th>Interviewer</th><th>Approval</th><th>Action</th></tr></thead>
              <tbody>
                {visibleItems.map(item => {
                  const pendingRequest = item.reschedule_requested_at && !item.reschedule_decision_status;
                  return (
                    <tr key={item.id}>
                      <td><b>{item.applications?.name_at_application}</b><small>{item.applications?.job_positions?.title}</small></td>
                      <td>{item.interview_type} · Round {item.round_number}<small>{item.interview_code}</small>{pendingRequest && <span className="tag alert-tag">Reschedule requested</span>}</td>
                      <td>{item.scheduled_start ? new Date(item.scheduled_start).toLocaleString() : "Not set"}</td>
                      <td>{item.user_profiles?.full_name || "Eligible suggestion pending"}</td>
                      <td><span className="status">{(item.assignment_status || "PENDING").replaceAll("_", " ")}</span></td>
                      <td className="action-cell">
                        <Link className="button small" href={`/dashboard/interviews/${item.id}`}>Open workspace</Link>
                        {canAssign && <button className="button small ghost" onClick={() => setSelected(item)}>Assign / change</button>}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          {!visibleItems.length && !error && <div className="notice">No interviews are available in this view.</div>}
        </section>

        {selected && (
          <div className="modal-backdrop">
            <form className="form-card modal-card" onSubmit={assign}>
              <div className="table-head"><h2>Approve interview assignment</h2><button type="button" className="icon-button" onClick={() => setSelected(null)}>×</button></div>
              <p><b>{selected.applications?.name_at_application}</b> — {selected.applications?.job_positions?.title}</p>
              <div className="notice">Eligible department: <b>{selected.applications?.job_positions?.department || "Not set"}</b>. HR is available as the controlled fallback.</div>
              <label>
                Eligible interviewer
                <select name="interviewer_id" defaultValue={selected.interviewer_id || ""} required>
                  <option value="" disabled>Select eligible staff</option>
                  {eligiblePeople.map(person => <option key={person.id} value={person.id}>{person.full_name} — {person.job_title || person.role} ({person.department || "HR"})</option>)}
                </select>
              </label>
              <label>Interview type<select name="interview_type" defaultValue={selected.interview_type || "Technical"}><option>Screening</option><option>Technical</option><option>HR</option><option>Managerial</option><option>Final</option></select></label>
              <label>Round<input name="round_number" type="number" min="1" max="20" defaultValue={selected.round_number || 1} /></label>
              <label>Planned duration<select name="duration_minutes" defaultValue="60"><option value="30">30 minutes</option><option value="45">45 minutes</option><option value="60">60 minutes</option><option value="90">90 minutes</option></select></label>
              <p className="muted">After approval, the assigned staff member chooses the exact date and time in their workspace.</p>
              <div className="actions"><button className="button">Approve assignment</button><button type="button" className="button ghost" onClick={() => setSelected(null)}>Cancel</button></div>
            </form>
          </div>
        )}
      </div>
    </div>
  );
}
