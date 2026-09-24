"use client";

import { FormEvent, Suspense, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { api, Job } from "@/lib/api";

function ApplicationForm() {
  const search = useSearchParams();
  const selected = search.get("job") || "";
  const [jobs, setJobs] = useState<Job[]>([]);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    api<{ items: Job[] }>("/jobs").then((result) => setJobs(result.items)).catch((reason) => setError(reason.message));
  }, []);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError("");
    const form = event.currentTarget;
    const data = new FormData(form);
    data.set("currency", "PKR");
    data.set("consent", data.get("consent") === "on" ? "true" : "false");
    try {
      const result = await api<{ message: string }>("/applications", { method: "POST", body: data });
      setMessage(result.message);
      form.reset();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Submission failed");
    } finally {
      setBusy(false);
    }
  }

  if (message) return <div className="success-panel"><span>✓</span><h2>Application received</h2><p>{message}</p><a className="button" href="/jobs">Return to open roles</a></div>;

  return (
    <form className="form-card" onSubmit={submit} encType="multipart/form-data">
      <div className="form-grid">
        <label className="wide">Position<select name="job_slug" defaultValue={selected} required><option value="">Select a role</option>{jobs.map((job) => <option key={job.id} value={job.slug}>{job.title}</option>)}</select></label>
        <label>Full name<input name="full_name" required minLength={2} /></label>
        <label>Email<input name="email" type="email" required /></label>
        <label>Phone<input name="phone" required /></label>
        <label>Years of experience<input name="experience_years" type="number" min="0" max="60" step="0.5" required /></label>
        <label className="wide">Skills <small>Separate with commas</small><input name="skills" placeholder="Python, FastAPI, SQL" required /></label>
        <label>Expected salary (PKR)<input name="expected_salary" type="number" min="0" required /></label>
        <label>Available joining date<input name="joining_date" type="date" required /></label>
        <label className="wide">CV <small>PDF or DOCX, maximum 10 MB</small><input name="cv" type="file" accept=".pdf,.docx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document" required /></label>
      </div>
      <label className="check"><input name="consent" type="checkbox" required /><span>I consent to NovaTech processing my information for recruitment purposes.</span></label>
      {error && <div className="notice error">{error}</div>}
      <button className="button full" disabled={busy}>{busy ? "Submitting…" : "Submit application"}</button>
    </form>
  );
}

export default function Apply() {
  return <div className="page"><section className="page-head compact"><div className="container"><span className="eyebrow">Application</span><h1>Tell us about yourself.</h1><p>No login needed. It usually takes less than five minutes.</p></div></section><section className="section"><div className="container narrow"><Suspense fallback={<div className="notice">Loading form…</div>}><ApplicationForm /></Suspense></div></section></div>;
}
