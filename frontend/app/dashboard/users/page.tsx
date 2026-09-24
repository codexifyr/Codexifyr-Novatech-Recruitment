"use client";

import { ChangeEvent, FormEvent, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import UserAccessEditor from "@/components/UserAccessEditor";

type StaffUser = {
  id: string;
  full_name: string;
  username: string;
  email: string;
  role: string;
  active: boolean;
  roles?: string[];
};

export default function UsersPage() {
  const router = useRouter();

  const [users, setUsers] = useState<StaffUser[]>([]);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function loadUsers() {
    try {
      const result = await api<{ items: StaffUser[] }>("/admin/users");
      setUsers(result.items);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Users could not load");
    }
  }

  useEffect(() => {
    loadUsers();
  }, [router]);

  async function createUser(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    setBusy(true);
    setError("");
    setMessage("");

    const form = new FormData(event.currentTarget);

    try {
      const result = await api<{ message: string }>("/admin/invitations", {
        method: "POST",
        body: JSON.stringify({
          full_name: form.get("full_name"),
          username: form.get("username"),
          email: form.get("email"),
          role: form.get("role"),
        }),
      });

      setMessage(result.message);
      event.currentTarget.reset();
      await loadUsers();
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "User could not be created",
      );
    } finally {
      setBusy(false);
    }
  }

  async function changeStatus(user: StaffUser) {
    setError("");
    setMessage("");

    try {
      await api(`/admin/users/${user.id}/status`, {
        method: "PATCH",
        body: JSON.stringify({
          active: !user.active,
        }),
      });

      setMessage("User status updated successfully.");
      await loadUsers();
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Status could not be updated",
      );
    }
  }

  async function changeRoles(user: StaffUser, event: ChangeEvent<HTMLSelectElement>) {
    const roles = Array.from(event.target.selectedOptions, option => option.value);
    if (!roles.length) return;
    try {
      await api(`/admin/users/${user.id}/access`, { method: "PUT", body: JSON.stringify({ roles, allowed_permissions: [], denied_permissions: [] }) });
      setMessage("User roles updated successfully."); await loadUsers();
    } catch (err) { setError(err instanceof Error ? err.message : "Roles could not be updated"); }
  }

  return (
    <div className="resource-page">
      <div className="container section">
        <Link className="back" href="/dashboard">
          ← Dashboard
        </Link>

        <span className="eyebrow">Administration</span>
        <h1>User Management</h1>

        <div className="detail-grid">
          <section className="table-card">
            <h2>Staff accounts</h2>

            <div className="table-scroll">
              <table>
                <thead>
                  <tr>
                    <th>Name</th>
                    <th>Username</th>
                    <th>Roles</th>
                    <th>Status</th>
                    <th>Action</th>
                  </tr>
                </thead>

                <tbody>
                  {users.map((user) => (
                    <tr key={user.id}>
                      <td>
                        <b>{user.full_name}</b>
                        <small>{user.email}</small>
                      </td>

                      <td>{user.username}</td>
                      <td><select multiple size={3} defaultValue={user.roles || [user.role]} onChange={event => changeRoles(user, event)} aria-label={`Roles for ${user.full_name}`}><option value="admin">Admin</option><option value="hr">HR</option><option value="recruiter">Recruiter</option><option value="hiring_manager">Hiring Manager</option><option value="interviewer">Interviewer</option><option value="operator">Operator</option></select><UserAccessEditor profileId={user.id} /></td>

                      <td>
                        <span className="status">
                          {user.active ? "ACTIVE" : "INACTIVE"}
                        </span>
                      </td>

                      <td>
                        <button
                          className="button small"
                          type="button"
                          onClick={() => changeStatus(user)}
                        >
                          {user.active ? "Deactivate" : "Activate"}
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>

          <form className="form-card" onSubmit={createUser}>
            <h2>Create staff account</h2>

            <label>
              Full name
              <input name="full_name" required minLength={2} />
            </label>

            <label>
              Username
              <input
                name="username"
                required
                minLength={3}
                pattern="[a-zA-Z0-9._-]+"
              />
            </label>

            <label>
              Email
              <input name="email" type="email" required />
            </label>

            <label>
              Role
              <select name="role" required>
                <option value="hr">HR</option>
                <option value="recruiter">Recruiter</option>
                <option value="interviewer">Interviewer</option>
                <option value="hiring_manager">Hiring Manager</option>
                <option value="operator">Operator</option>
                <option value="admin">Admin</option>
              </select>
            </label>

            {message && <div className="notice success">{message}</div>}
            {error && <div className="notice error">{error}</div>}

            <button className="button full" disabled={busy}>
              {busy ? "Sending…" : "Send invitation"}
            </button>
          </form>
        </div>
      </div>
    </div>
  );
}