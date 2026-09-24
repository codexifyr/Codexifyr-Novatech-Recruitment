"use client";

import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import styles from "./portal.module.css";

type Profile = {
  id?: string;
  full_name: string;
  username: string;
  email: string;
  role: string;
  timezone?: string;
  avatar_url?: string;
  job_title?: string;
  department?: string;
  must_change_password?: boolean;
};

type CandidateDocument = {
  id: string;
  document_type: string;
  file_name: string;
  verification_status: string;
  created_at?: string;
};

type Employee = {
  id: string;
  employee_code?: string;
  department?: string;
  start_date?: string;
};

type Application = {
  id: string;
  job_positions?: {
    title?: string;
    department?: string;
  } | null;
};

type PortalData = {
  applications?: Application[];
  documents?: CandidateDocument[];
  employee?: Employee | null;
};

type TaskKey = "personal" | "photo" | "documents" | "security";

const taskCopy: Record<TaskKey, { title: string; description: string; number: string }> = {
  personal: {
    number: "01",
    title: "Personal information",
    description: "Confirm your name, username and preferred timezone.",
  },
  photo: {
    number: "02",
    title: "Profile photo",
    description: "Upload a clear JPG, PNG or WebP profile image.",
  },
  documents: {
    number: "03",
    title: "Required documents",
    description: "Provide one identity document and one education document.",
  },
  security: {
    number: "04",
    title: "Account security",
    description: "Confirm your secure account password.",
  },
};

function normalize<T>(value: T[] | T | null | undefined): T[] {
  if (Array.isArray(value)) return value;
  return value ? [value] : [];
}

function documentMatches(document: CandidateDocument, words: string[]) {
  const value = `${document.document_type} ${document.file_name}`.toLowerCase();
  return words.some(word => value.includes(word));
}

function formatDate(value?: string) {
  if (!value) return "To be confirmed";
  return new Intl.DateTimeFormat("en-PK", {
    day: "2-digit",
    month: "short",
    year: "numeric",
    timeZone: "Asia/Karachi",
  }).format(new Date(`${value}T00:00:00`));
}

export default function CandidatePortalPage() {
  const router = useRouter();
  const [profile, setProfile] = useState<Profile | null>(null);
  const [portal, setPortal] = useState<PortalData | null>(null);
  const [activeTask, setActiveTask] = useState<TaskKey>("personal");
  const [busy, setBusy] = useState<string | null>(null);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setError("");
    try {
      const [authResult, portalResult] = await Promise.all([
        api<{ user: Profile }>("/auth/me"),
        api<PortalData>("/candidate/portal"),
      ]);

      if (!["candidate", "employee"].includes(authResult.user.role)) {
        router.replace("/dashboard");
        return;
      }

      setProfile(authResult.user);
      setPortal(portalResult);
    } catch (caught) {
      const reason = caught instanceof Error ? caught.message : "Your onboarding workspace could not be loaded.";
      setError(reason);
      if (reason.toLowerCase().includes("unauthor")) router.replace("/login");
    }
  }, [router]);

  useEffect(() => {
    void load();
  }, [load]);

  const documents = useMemo(() => normalize(portal?.documents), [portal?.documents]);
  const applications = useMemo(() => normalize(portal?.applications), [portal?.applications]);
  const currentApplication = applications[0];
  const employee = portal?.employee || null;
  const position = currentApplication?.job_positions?.title || "New team member";
  const department = employee?.department || currentApplication?.job_positions?.department || "NovaTech Solutions";

  const identityComplete = documents.some(document =>
    documentMatches(document, ["identity", "cnic", "passport", "national id"]),
  );
  const educationComplete = documents.some(document =>
    documentMatches(document, ["education", "degree", "certificate", "transcript"]),
  );

  const completion: Record<TaskKey, boolean> = {
    personal: Boolean(profile?.full_name?.trim() && profile?.username?.trim() && profile?.timezone?.trim()),
    photo: Boolean(profile?.avatar_url),
    documents: identityComplete && educationComplete,
    security: profile?.must_change_password === false,
  };

  const completedCount = Object.values(completion).filter(Boolean).length;
  const completionPercent = completedCount * 25;

  function show(task: TaskKey) {
    setMessage("");
    setError("");
    setActiveTask(task);
    requestAnimationFrame(() => {
      document.getElementById("onboarding-task-panel")?.scrollIntoView({ behavior: "smooth", block: "start" });
    });
  }

  async function savePersonal(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!profile) return;
    setBusy("personal");
    setError("");
    setMessage("");
    const form = new FormData(event.currentTarget);

    try {
      const result = await api<{ data: Profile; message: string }>("/auth/me", {
        method: "PATCH",
        body: JSON.stringify({
          full_name: String(form.get("full_name") || "").trim(),
          username: String(form.get("username") || "").trim(),
          timezone: String(form.get("timezone") || "Asia/Karachi"),
          job_title: profile.job_title || null,
          department: profile.department || null,
          avatar_url: profile.avatar_url || null,
        }),
      });
      setProfile(current => ({ ...(current || profile), ...result.data }));
      setMessage(result.message || "Personal information saved.");
      window.dispatchEvent(new Event("novatech-auth-changed"));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Personal information could not be saved.");
    } finally {
      setBusy(null);
    }
  }

  async function uploadPhoto(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy("photo");
    setError("");
    setMessage("");
    try {
      const result = await api<{ data: { avatar_url: string }; message: string }>("/auth/me/avatar", {
        method: "POST",
        body: new FormData(event.currentTarget),
      });
      setProfile(current => (current ? { ...current, avatar_url: result.data.avatar_url } : current));
      event.currentTarget.reset();
      setMessage(result.message || "Profile photo updated.");
      window.dispatchEvent(new Event("novatech-auth-changed"));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Profile photo could not be uploaded.");
    } finally {
      setBusy(null);
    }
  }

  async function uploadDocument(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy("documents");
    setError("");
    setMessage("");
    try {
      const result = await api<{ message: string }>("/candidate/documents", {
        method: "POST",
        body: new FormData(event.currentTarget),
      });
      event.currentTarget.reset();
      setMessage(result.message || "Document uploaded for HR review.");
      await load();
      setActiveTask("documents");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Document could not be uploaded.");
    } finally {
      setBusy(null);
    }
  }

  async function downloadDocument(documentId: string) {
    setError("");
    try {
      const result = await api<{ url: string }>(`/candidate/documents/${documentId}/download`);
      window.open(result.url, "_blank", "noopener,noreferrer");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Document could not be opened.");
    }
  }

  async function changePassword(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    setMessage("");
    const form = new FormData(event.currentTarget);
    const password = String(form.get("password") || "");
    const confirmation = String(form.get("confirmation") || "");
    if (password !== confirmation) {
      setError("Passwords do not match.");
      return;
    }

    setBusy("security");
    try {
      const result = await api<{ message: string }>("/auth/password/change", {
        method: "POST",
        body: JSON.stringify({ password }),
      });
      setProfile(current => (current ? { ...current, must_change_password: false } : current));
      event.currentTarget.reset();
      setMessage(result.message || "Password updated successfully.");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Password could not be changed.");
    } finally {
      setBusy(null);
    }
  }

  if (!profile || !portal) {
    return (
      <main className={styles.page}>
        <div className={styles.loadingCard}>
          <span className={styles.spinner} />
          <p>{error || "Opening your onboarding workspace..."}</p>
        </div>
      </main>
    );
  }

  return (
    <main className={styles.page}>
      <section className={styles.shell}>
        <header className={styles.hero}>
          <div className={styles.identity}>
            {profile.avatar_url ? (
              <img className={styles.avatar} src={profile.avatar_url} alt="" />
            ) : (
              <div className={styles.avatarFallback} aria-hidden="true">
                {profile.full_name
                  .split(" ")
                  .map(part => part[0])
                  .join("")
                  .slice(0, 2)
                  .toUpperCase()}
              </div>
            )}
            <div>
              <span className={styles.eyebrow}>Employee onboarding</span>
              <h1>Welcome, {profile.full_name}</h1>
              <p>{position} · {department}</p>
            </div>
          </div>

          <div className={styles.employeeMeta}>
            <div>
              <span>Employee ID</span>
              <strong>{employee?.employee_code || "Pending"}</strong>
            </div>
            <div>
              <span>Joining date</span>
              <strong>{formatDate(employee?.start_date)}</strong>
            </div>
          </div>
        </header>

        <section className={styles.progressCard} aria-label="Onboarding progress">
          <div className={styles.progressHeader}>
            <div>
              <span className={styles.eyebrow}>Profile setup</span>
              <h2>{completedCount} of 4 tasks completed</h2>
            </div>
            <strong>{completionPercent}%</strong>
          </div>
          <div className={styles.progressTrack}>
            <span style={{ width: `${completionPercent}%` }} />
          </div>
          <p>
            {completedCount === 4
              ? "Your profile is ready for HR verification."
              : "Complete the remaining tasks so HR can verify your onboarding profile."}
          </p>
        </section>

        {message && <div className={styles.success}>{message}</div>}
        {error && <div className={styles.error}>{error}</div>}

        <section className={styles.workspace}>
          <nav className={styles.taskList} aria-label="Profile setup tasks">
            {(Object.keys(taskCopy) as TaskKey[]).map(key => {
              const task = taskCopy[key];
              return (
                <button
                  type="button"
                  key={key}
                  className={`${styles.taskButton} ${activeTask === key ? styles.activeTask : ""}`}
                  onClick={() => show(key)}
                >
                  <span className={styles.taskNumber}>{completion[key] ? "✓" : task.number}</span>
                  <span>
                    <strong>{task.title}</strong>
                    <small>{task.description}</small>
                  </span>
                  <span className={completion[key] ? styles.done : styles.pending}>
                    {completion[key] ? "Complete" : "Required"}
                  </span>
                </button>
              );
            })}
          </nav>

          <section id="onboarding-task-panel" className={styles.taskPanel}>
            {activeTask === "personal" && (
              <form onSubmit={savePersonal}>
                <div className={styles.panelHeading}>
                  <div>
                    <span className={styles.eyebrow}>Task 1</span>
                    <h2>Personal information</h2>
                  </div>
                  <span className={completion.personal ? styles.done : styles.pending}>
                    {completion.personal ? "Complete" : "Required"}
                  </span>
                </div>
                <div className={styles.formGrid}>
                  <label>
                    Full name
                    <input name="full_name" defaultValue={profile.full_name} required minLength={2} />
                  </label>
                  <label>
                    Username
                    <input name="username" defaultValue={profile.username} required minLength={3} />
                  </label>
                  <label className={styles.fullField}>
                    Email address
                    <input value={profile.email} disabled />
                    <small>Your verified login email cannot be changed here.</small>
                  </label>
                  <label className={styles.fullField}>
                    Timezone
                    <select name="timezone" defaultValue={profile.timezone || "Asia/Karachi"}>
                      <option value="Asia/Karachi">Pakistan Standard Time</option>
                      <option value="UTC">UTC</option>
                      <option value="Asia/Dubai">Gulf Standard Time</option>
                      <option value="Europe/London">United Kingdom</option>
                    </select>
                  </label>
                </div>
                <button className={styles.primaryButton} disabled={busy === "personal"}>
                  {busy === "personal" ? "Saving..." : "Save personal information"}
                </button>
              </form>
            )}

            {activeTask === "photo" && (
              <form onSubmit={uploadPhoto}>
                <div className={styles.panelHeading}>
                  <div>
                    <span className={styles.eyebrow}>Task 2</span>
                    <h2>Profile photo</h2>
                  </div>
                  <span className={completion.photo ? styles.done : styles.pending}>
                    {completion.photo ? "Complete" : "Required"}
                  </span>
                </div>
                <div className={styles.photoEditor}>
                  {profile.avatar_url ? (
                    <img src={profile.avatar_url} alt="Current profile" />
                  ) : (
                    <div className={styles.photoPlaceholder}>Add photo</div>
                  )}
                  <div>
                    <p>Use a clear, recent head-and-shoulders photo.</p>
                    <small>JPG, PNG or WebP. Maximum file size 5 MB.</small>
                    <input name="file" type="file" accept=".jpg,.jpeg,.png,.webp" required />
                  </div>
                </div>
                <button className={styles.primaryButton} disabled={busy === "photo"}>
                  {busy === "photo" ? "Uploading..." : "Upload profile photo"}
                </button>
              </form>
            )}

            {activeTask === "documents" && (
              <div>
                <div className={styles.panelHeading}>
                  <div>
                    <span className={styles.eyebrow}>Task 3</span>
                    <h2>Required documents</h2>
                  </div>
                  <span className={completion.documents ? styles.done : styles.pending}>
                    {completion.documents ? "Complete" : "Required"}
                  </span>
                </div>

                <div className={styles.documentChecklist}>
                  <div className={identityComplete ? styles.checkedItem : ""}>
                    <span>{identityComplete ? "✓" : "1"}</span>
                    <div><strong>Identity document</strong><small>CNIC or passport</small></div>
                  </div>
                  <div className={educationComplete ? styles.checkedItem : ""}>
                    <span>{educationComplete ? "✓" : "2"}</span>
                    <div><strong>Education document</strong><small>Degree, transcript or certificate</small></div>
                  </div>
                </div>

                <form className={styles.uploadForm} onSubmit={uploadDocument}>
                  <label>
                    Document category
                    <select name="document_type" required defaultValue="Identity document">
                      <option value="Identity document">Identity document</option>
                      <option value="Education certificate">Education certificate</option>
                    </select>
                  </label>
                  <label>
                    Select file
                    <input name="file" type="file" accept=".pdf,.docx,.jpg,.jpeg,.png" required />
                  </label>
                  <button className={styles.primaryButton} disabled={busy === "documents"}>
                    {busy === "documents" ? "Uploading..." : "Upload document"}
                  </button>
                </form>

                {documents.length > 0 && (
                  <div className={styles.documentList}>
                    <h3>Uploaded documents</h3>
                    {documents.map(document => (
                      <div key={document.id}>
                        <span>
                          <strong>{document.file_name}</strong>
                          <small>{document.document_type}</small>
                        </span>
                        <span className={styles.documentActions}>
                          <em>{document.verification_status}</em>
                          <button type="button" onClick={() => void downloadDocument(document.id)}>View</button>
                        </span>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}

            {activeTask === "security" && (
              <form onSubmit={changePassword}>
                <div className={styles.panelHeading}>
                  <div>
                    <span className={styles.eyebrow}>Task 4</span>
                    <h2>Account security</h2>
                  </div>
                  <span className={completion.security ? styles.done : styles.pending}>
                    {completion.security ? "Complete" : "Required"}
                  </span>
                </div>
                <p className={styles.panelIntro}>Use at least 10 characters. A longer passphrase is recommended.</p>
                <div className={styles.formGrid}>
                  <label>
                    New password
                    <input name="password" type="password" minLength={10} autoComplete="new-password" required />
                  </label>
                  <label>
                    Confirm password
                    <input name="confirmation" type="password" minLength={10} autoComplete="new-password" required />
                  </label>
                </div>
                <button className={styles.primaryButton} disabled={busy === "security"}>
                  {busy === "security" ? "Updating..." : "Update password"}
                </button>
              </form>
            )}
          </section>
        </section>
      </section>
    </main>
  );
}
