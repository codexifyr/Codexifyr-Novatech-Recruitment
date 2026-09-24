"use client";

import { FormEvent, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import NotificationPreferences from "@/components/NotificationPreferences";

type Profile = {
  full_name: string;
  username: string;
  email: string;
  role: string;
  department?: string;
  job_title?: string;
  avatar_url?: string;
  timezone?: string;
  must_change_password?: boolean;
};

export default function AccountPage() {
  const router = useRouter();
  const [profile, setProfile] = useState<Profile | null>(null);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    api<{ user: Profile }>("/auth/me")
      .then(result => {
        if (["candidate", "employee"].includes(result.user.role)) {
          router.replace("/portal");
          return;
        }
        setProfile(result.user);
      })
      .catch(caught => {
        setError(caught instanceof Error ? caught.message : "Account could not be loaded.");
        router.replace("/login");
      });
  }, [router]);

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!profile) return;
    setError("");
    setMessage("");
    const form = new FormData(event.currentTarget);
    try {
      const result = await api<{ data: Profile; message: string }>("/auth/me", {
        method: "PATCH",
        body: JSON.stringify({
          full_name: form.get("full_name"),
          username: form.get("username"),
          job_title: form.get("job_title") || null,
          department: form.get("department") || null,
          avatar_url: profile.avatar_url || null,
          timezone: form.get("timezone"),
        }),
      });
      setProfile(current => ({ ...(current || profile), ...result.data }));
      setMessage(result.message);
      window.dispatchEvent(new Event("novatech-auth-changed"));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Profile update failed.");
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
    try {
      const result = await api<{ message: string }>("/auth/password/change", {
        method: "POST",
        body: JSON.stringify({ password }),
      });
      setMessage(result.message);
      event.currentTarget.reset();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Password change failed.");
    }
  }

  async function uploadAvatar(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    setMessage("");
    try {
      const result = await api<{ data: { avatar_url: string }; message: string }>("/auth/me/avatar", {
        method: "POST",
        body: new FormData(event.currentTarget),
      });
      setProfile(current => (current ? { ...current, avatar_url: result.data.avatar_url } : current));
      setMessage(result.message);
      event.currentTarget.reset();
      window.dispatchEvent(new Event("novatech-auth-changed"));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Profile photo upload failed.");
    }
  }

  if (!profile) {
    return (
      <div className="container section">
        <div className="notice">{error || "Loading account..."}</div>
      </div>
    );
  }

  return (
    <div className="resource-page">
      <div className="container section">
        <Link className="back" href="/dashboard">← Dashboard</Link>
        <span className="eyebrow">Personal settings</span>
        <h1>My account</h1>

        {profile.must_change_password && (
          <div className="notice error">For security, change your temporary password before continuing.</div>
        )}
        {message && <div className="notice success">{message}</div>}
        {error && <div className="notice error">{error}</div>}

        <div className="detail-grid">
          <form className="form-card" onSubmit={save}>
            <h2>Profile</h2>
            <label>Full name<input name="full_name" defaultValue={profile.full_name} required /></label>
            <label>Username<input name="username" defaultValue={profile.username} required /></label>
            <label>Email<input value={profile.email} disabled /></label>
            <label>Job title<input name="job_title" defaultValue={profile.job_title || ""} /></label>
            <label>Department<input name="department" defaultValue={profile.department || ""} /></label>
            <label>Timezone<input name="timezone" defaultValue={profile.timezone || "Asia/Karachi"} /></label>
            <button className="button">Save profile</button>
          </form>

          <form className="form-card" onSubmit={uploadAvatar}>
            <h2>Profile photo</h2>
            <p className="muted">JPG, PNG or WebP up to 5 MB.</p>
            <input name="file" type="file" accept=".jpg,.jpeg,.png,.webp" required />
            <button className="button">Upload photo</button>
          </form>

          <form className="form-card" onSubmit={changePassword}>
            <h2>Security</h2>
            <p className="muted">Use at least 10 characters. A longer passphrase is recommended.</p>
            <label>New password<input name="password" type="password" minLength={10} required /></label>
            <label>Confirm password<input name="confirmation" type="password" minLength={10} required /></label>
            <button className="button">Change password</button>
          </form>

          <NotificationPreferences />
        </div>
      </div>
    </div>
  );
}
