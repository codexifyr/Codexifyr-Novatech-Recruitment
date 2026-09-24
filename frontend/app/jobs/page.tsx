"use client";
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { api, Job } from "@/lib/api";

export default function Jobs() {
  const [jobs, setJobs] = useState<Job[]>([]), [query, setQuery] = useState(""), [department, setDepartment] = useState("All");
  const [loading, setLoading] = useState(true), [error, setError] = useState("");
  useEffect(() => { api<{items: Job[]}>("/jobs").then(r => setJobs(r.items)).catch(e => setError(e.message)).finally(() => setLoading(false)); }, []);
  const departments = ["All", ...Array.from(new Set(jobs.map(j => j.department)))];
  const filtered = useMemo(() => jobs.filter(j => (department === "All" || j.department === department) && `${j.title} ${j.department} ${j.location}`.toLowerCase().includes(query.toLowerCase())), [jobs, query, department]);
  return <div className="page"><section className="page-head"><div className="container"><span className="eyebrow">Open opportunities</span><h1>Find the work that fits you.</h1><p>Explore roles across our growing teams.</p></div></section><section className="section"><div className="container">
    <div className="filters"><input aria-label="Search jobs" placeholder="Search title, team or location" value={query} onChange={e => setQuery(e.target.value)}/><select aria-label="Department" value={department} onChange={e => setDepartment(e.target.value)}>{departments.map(d => <option key={d}>{d}</option>)}</select></div>
    {loading && <div className="notice">Loading open positions…</div>}{error && <div className="notice error">{error}</div>}
    <div className="job-list">{filtered.map(job => <article className="job-card" key={job.id}><div><span className="tag">{job.department}</span><h2>{job.title}</h2><p>{job.description}</p><div className="job-meta"><span>⌖ {job.location}</span><span>◷ {job.employment_type}</span><span>◉ {job.workplace_type}</span></div></div><Link className="arrow-link" href={`/jobs/${job.slug}`}>View role →</Link></article>)}</div>
    {!loading && !error && !filtered.length && <div className="notice">No roles match your filters right now.</div>}
  </div></section></div>;
}

