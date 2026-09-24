"use client";

import Link from "next/link";
import { FormEvent, Suspense, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { api } from "@/lib/api";

function InviteForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    setMessage("");
    const data = new FormData(event.currentTarget);
    const password = String(data.get("password"));
    if (password !== String(data.get("confirm_password"))) {
      setError("Passwords do not match.");
      return;
    }
    setBusy(true);
    try {
      const result = await api<{ message: string }>("/auth/invitations/accept", {
        method: "POST",
        body: JSON.stringify({ token: searchParams.get("token") || "", username: data.get("username"), password }),
      });
      setMessage(result.message);
      setTimeout(() => router.push("/login"), 900);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Invitation could not be accepted.");
    } finally {
      setBusy(false);
    }
  }

  return <div className="auth-page"><div className="auth-card"><span className="brand-mark large-mark">N</span><span className="eyebrow">NovaTech team access</span><h1>Complete your invitation.</h1><p>Choose your username and a secure password to activate your account.</p><form onSubmit={submit}><label>Username<input name="username" required minLength={3} pattern="[a-zA-Z0-9._-]+" autoComplete="username" /></label><label>Password<input name="password" type="password" required minLength={10} autoComplete="new-password" /></label><label>Confirm password<input name="confirm_password" type="password" required minLength={10} autoComplete="new-password" /></label>{message && <div className="notice success">{message}</div>}{error && <div className="notice error">{error}</div>}<button className="button full" disabled={busy}>{busy ? "Activating..." : "Activate account"}</button></form><Link className="text-link" href="/login">Already activated? Sign in</Link></div></div>;
}

export default function InvitePage() {
  return <Suspense fallback={<div className="auth-page"><div className="auth-card"><div className="notice">Loading invitation...</div></div></div>}><InviteForm /></Suspense>;
}
