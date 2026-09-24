"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api";

type User = {
  id: string;
  full_name: string;
  role: string;
};

type Meeting = {
  id: string;
  interview_code: string;
  status: string;
  assignment_status: string;
  interview_type: string;
  round_number: number;
  scheduled_start: string;
  scheduled_end: string;
  schedule_timezone?: string;
  meeting_url?: string;
  meeting_code?: string;
  google_event_url?: string;
  interviewer_id?: string;
  starts_in_minutes?: number;
  join_available?: boolean;
  applications?: {
    id: string;
    application_code: string;
    name_at_application: string;
    email_at_application: string;
    job_positions?: {
      title: string;
      department: string;
    };
  };
  user_profiles?: {
    id: string;
    full_name: string;
    email: string;
    role: string;
    department?: string;
    job_title?: string;
  };
};

function countdown(minutes?: number) {
  if (minutes === undefined || minutes === null) {
    return "—";
  }

  if (minutes <= 0) {
    return "Starting now";
  }

  if (minutes < 60) {
    return `In ${minutes} minutes`;
  }

  if (minutes < 1440) {
    const hours = Math.floor(minutes / 60);
    const remainingMinutes = minutes % 60;

    return remainingMinutes
      ? `In ${hours}h ${remainingMinutes}m`
      : `In ${hours} hours`;
  }

  const days = Math.floor(minutes / 1440);
  return `In ${days} day${days === 1 ? "" : "s"}`;
}

export default function UpcomingMeetingsPage() {
  const [user, setUser] = useState<User | null>(null);
  const [items, setItems] = useState<Meeting[]>([]);
  const [staffFilter, setStaffFilter] = useState("");
  const [range, setRange] = useState("30");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  async function load() {
    try {
      const [account, meetings] = await Promise.all([
        api<{ user: User }>("/auth/me"),
        api<{ items: Meeting[] }>(
          `/admin/upcoming-meetings?days=${range}`
        ),
      ]);

      setUser(account.user);
      setItems(meetings.items);
      setError("");
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "Upcoming meetings could not load"
      );
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    setLoading(true);
    load();

    const refreshTimer = window.setInterval(load, 60_000);

    return () => window.clearInterval(refreshTimer);
  }, [range]);

  const interviewers = useMemo(() => {
    const people = new Map<string, string>();

    items.forEach((meeting) => {
      if (meeting.user_profiles?.id) {
        people.set(
          meeting.user_profiles.id,
          meeting.user_profiles.full_name
        );
      }
    });

    return Array.from(people.entries()).sort((a, b) =>
      a[1].localeCompare(b[1])
    );
  }, [items]);

  const visibleItems = useMemo(() => {
    if (!staffFilter) {
      return items;
    }

    return items.filter(
      (meeting) => meeting.interviewer_id === staffFilter
    );
  }, [items, staffFilter]);

  const today = new Date().toDateString();

  const todayCount = visibleItems.filter(
    (meeting) =>
      new Date(meeting.scheduled_start).toDateString() === today
  ).length;

  const pendingConfirmations = visibleItems.filter(
    (meeting) => meeting.status === "PENDING_CONFIRMATION"
  ).length;

  const startingSoon = visibleItems.filter(
    (meeting) =>
      meeting.starts_in_minutes !== undefined &&
      meeting.starts_in_minutes >= 0 &&
      meeting.starts_in_minutes <= 60
  ).length;

  return (
    <div className="resource-page">
      <div className="container section">
        <Link className="back" href="/dashboard">
          ← Dashboard
        </Link>

        <span className="eyebrow">Calendar & interviews</span>

        <h1>
          {user?.role === "admin"
            ? "Company upcoming meetings"
            : "My upcoming meetings"}
        </h1>

        <p className="lead small">
          {user?.role === "admin"
            ? "View which staff member is meeting which candidate, along with the schedule and Google Meet details."
            : "Your scheduled candidate interviews and Google Meet details appear here automatically."}
        </p>

        {error && <div className="notice error">{error}</div>}

        <div className="metric-cards">
          <article>
            <span>Upcoming</span>
            <b>{visibleItems.length}</b>
          </article>

          <article>
            <span>Today</span>
            <b>{todayCount}</b>
          </article>

          <article>
            <span>Starting within 1 hour</span>
            <b>{startingSoon}</b>
          </article>

          <article>
            <span>Candidate confirmation pending</span>
            <b>{pendingConfirmations}</b>
          </article>
        </div>

        <section className="form-card">
          <div className="filters">
            <label>
              Date range
              <select
                value={range}
                onChange={(event) => setRange(event.target.value)}
              >
                <option value="7">Next 7 days</option>
                <option value="30">Next 30 days</option>
                <option value="60">Next 60 days</option>
                <option value="90">Next 90 days</option>
              </select>
            </label>

            {user?.role === "admin" && (
              <label>
                Staff member
                <select
                  value={staffFilter}
                  onChange={(event) =>
                    setStaffFilter(event.target.value)
                  }
                >
                  <option value="">All assigned staff</option>

                  {interviewers.map(([id, name]) => (
                    <option key={id} value={id}>
                      {name}
                    </option>
                  ))}
                </select>
              </label>
            )}
          </div>
        </section>

        <section className="table-card">
          <div className="table-head">
            <h2>Meeting schedule</h2>

            <button
              className="button small ghost"
              onClick={() => {
                setLoading(true);
                load();
              }}
              disabled={loading}
            >
              {loading ? "Refreshing…" : "Refresh"}
            </button>
          </div>

          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>Date & time</th>
                  <th>Candidate</th>
                  <th>Position</th>

                  {user?.role === "admin" && (
                    <th>Assigned staff</th>
                  )}

                  <th>Status</th>
                  <th>Starts</th>
                  <th>Actions</th>
                </tr>
              </thead>

              <tbody>
                {visibleItems.map((meeting) => (
                  <tr key={meeting.id}>
                    <td>
                      <b>
                        {new Date(
                          meeting.scheduled_start
                        ).toLocaleDateString()}
                      </b>

                      <small>
                        {new Date(
                          meeting.scheduled_start
                        ).toLocaleTimeString([], {
                          hour: "2-digit",
                          minute: "2-digit",
                        })}
                        {" – "}
                        {new Date(
                          meeting.scheduled_end
                        ).toLocaleTimeString([], {
                          hour: "2-digit",
                          minute: "2-digit",
                        })}
                      </small>
                    </td>

                    <td>
                      <b>
                        {meeting.applications?.name_at_application ||
                          "—"}
                      </b>

                      <small>
                        {meeting.applications?.email_at_application}
                      </small>
                    </td>

                    <td>
                      {meeting.applications?.job_positions?.title ||
                        "—"}

                      <small>
                        {
                          meeting.applications?.job_positions
                            ?.department
                        }
                      </small>
                    </td>

                    {user?.role === "admin" && (
                      <td>
                        <b>
                          {meeting.user_profiles?.full_name ||
                            "Not assigned"}
                        </b>

                        <small>
                          {meeting.user_profiles?.job_title ||
                            meeting.user_profiles?.role}
                        </small>
                      </td>
                    )}

                    <td>
                      <span className="status">
                        {meeting.status.replaceAll("_", " ")}
                      </span>
                    </td>

                    <td>
                      {countdown(meeting.starts_in_minutes)}
                    </td>

                    <td>
                      <div className="button-row">
                        <Link
                          className="button small ghost"
                          href={`/dashboard/interviews/${meeting.id}`}
                        >
                          Workspace
                        </Link>

                        {meeting.meeting_url && (
                          <a
                            className="button small"
                            href={meeting.meeting_url}
                            target="_blank"
                            rel="noreferrer"
                          >
                            {meeting.join_available
                              ? "Join now"
                              : "Open Meet"}
                          </a>
                        )}

                        {meeting.google_event_url && (
                          <a
                            className="text-link"
                            href={meeting.google_event_url}
                            target="_blank"
                            rel="noreferrer"
                          >
                            Calendar
                          </a>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {!loading && visibleItems.length === 0 && (
            <div className="notice">
              No upcoming meetings are scheduled for this period.
            </div>
          )}
        </section>
      </div>
    </div>
  );
}