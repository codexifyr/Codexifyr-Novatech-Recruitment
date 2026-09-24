"use client";
import Link from "next/link";
import { FormEvent, useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
export default function Login() {
	const router=useRouter(),[error,setError]=useState(""),[busy,setBusy]=useState(false);
	async function submit(e:FormEvent<HTMLFormElement>){e.preventDefault();setBusy(true);setError("");const d=new FormData(e.currentTarget);try{const r=await api<{user:{role?:string;must_change_password?:boolean};requires_persona?:boolean}>("/auth/login",{method:"POST",body:JSON.stringify({identifier:d.get("identifier"),password:d.get("password")})});window.dispatchEvent(new Event("novatech-auth-changed"));const portalUser=r.user.role==="candidate"||r.user.role==="employee";router.push(r.requires_persona?"/staff-select":r.user.must_change_password?"/account":portalUser?"/portal":"/dashboard");}catch(err){setError(err instanceof Error?err.message:"Login failed");}finally{setBusy(false)}}
	return <div className="auth-page"><div className="auth-card"><span className="brand-mark large-mark">N</span><span className="eyebrow">Secure account access</span><h1>Welcome back.</h1><p>Use your username or registered email.</p><form onSubmit={submit}><label>Username or email<input name="identifier" autoComplete="username" required/></label><label>Password<input name="password" type="password" autoComplete="current-password" required minLength={8}/></label>{error&&<div className="notice error">{error}</div>}<button className="button full" disabled={busy}>{busy?"Signing in...":"Sign in"}</button></form><Link className="text-link" href="/forgot-password">Forgot your password?</Link><small>Candidate accounts are invited when an application reaches the interview process.</small></div></div>;
}
