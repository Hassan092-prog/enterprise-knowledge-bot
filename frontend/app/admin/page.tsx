"use client";

import { useState, useRef, useEffect } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://192.168.1.92:8000";

type Stats = {
  users: number;
  sessions: number;
  total_chunks: number;
  documents: string[];
};

type RoleRequest = {
  id: number;
  user_id: number;
  username: string;
  requested_role: string;
  created_at: string;
};

type UserData = {
  id: number;
  username: string;
  role: string;
  created_at: string;
};

export default function AdminDashboard() {
  const [stats, setStats] = useState<Stats | null>(null);
  const [requests, setRequests] = useState<RoleRequest[]>([]);
  const [users, setUsers] = useState<UserData[]>([]);
  const [isUploading, setIsUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  
  const fileInputRef = useRef<HTMLInputElement>(null);
  const router = useRouter();

  const authFetch = async (url: string, options: RequestInit = {}) => {
    const token = localStorage.getItem("token");
    if (!token) {
      router.push("/login");
      throw new Error("No token found");
    }
    const headers = {
      ...options.headers,
      Authorization: `Bearer ${token}`,
    };
    const res = await fetch(url, { ...options, headers });
    if (res.status === 401 || res.status === 403) {
      router.push("/");
      throw new Error("Unauthorized");
    }
    return res;
  };

  const fetchStats = async () => {
    try {
      const res = await authFetch(`${API_URL}/admin/stats`);
      if (res.ok) {
        const data = await res.json();
        setStats(data);
      }
      
      const reqRes = await authFetch(`${API_URL}/admin/requests`);
      if (reqRes.ok) {
        setRequests(await reqRes.json());
      }
      
      const usersRes = await authFetch(`${API_URL}/admin/users`);
      if (usersRes.ok) {
        setUsers(await usersRes.json());
      }
    } catch (err: unknown) {
      if (err instanceof Error) {
        setError(err.message);
      } else {
        setError("Failed to load stats");
      }
    }
  };

  useEffect(() => {
    fetchStats();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const handleUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    setIsUploading(true);
    const formData = new FormData();
    formData.append("file", file);

    try {
      const res = await authFetch(`${API_URL}/admin/upload_global`, {
        method: "POST",
        body: formData,
      });

      if (res.ok) {
        await fetchStats();
      } else {
        const err = await res.json();
        alert(`Upload failed: ${err.detail}`);
      }
    } catch (error) {
      console.error("Upload error:", error);
      alert("Failed to connect to backend for upload.");
    } finally {
      setIsUploading(false);
      if (fileInputRef.current) {
        fileInputRef.current.value = "";
      }
    }
  };

  const handleDelete = async (filename: string) => {
    try {
      const res = await authFetch(`${API_URL}/admin/documents_global/${filename}`, {
        method: "DELETE",
      });
      if (res.ok) {
        await fetchStats();
      }
    } catch (error) {
      console.error("Delete error:", error);
    }
  };

  const handleApprove = async (id: number) => {
    try {
      const res = await authFetch(`${API_URL}/admin/requests/${id}/approve`, { method: "POST" });
      if (res.ok) await fetchStats();
    } catch (err) { console.error(err); }
  };

  const handleReject = async (id: number) => {
    try {
      const res = await authFetch(`${API_URL}/admin/requests/${id}/reject`, { method: "POST" });
      if (res.ok) await fetchStats();
    } catch (err) { console.error(err); }
  };

  const handleChangeRole = async (userId: number, role: string) => {
    try {
      const res = await authFetch(`${API_URL}/admin/users/${userId}/role`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ role })
      });
      if (res.ok) await fetchStats();
      else alert("Failed to change role");
    } catch (err) { console.error(err); }
  };

  return (
    <div className="min-h-screen bg-paper text-ink font-sans p-8 relative overflow-hidden">
      {/* Atmospheric Radial Blooms */}
      <div className="absolute top-[-200px] right-[-100px] w-[600px] h-[600px] rounded-full bg-accent opacity-[0.07] blur-[100px] pointer-events-none" />
      
      <div className="max-w-4xl mx-auto space-y-8 relative z-10">
        
        <div className="flex justify-between items-center bg-paper-2 p-6 rounded-base border border-border shadow-[0_8px_30px_rgb(0,0,0,0.12)]">
          <div>
            <h1 className="text-2xl font-display font-semibold text-ink tracking-tight">
              Admin Dashboard
            </h1>
            <p className="text-muted text-sm mt-1">Manage global documents and view statistics</p>
          </div>
          <Link href="/" className="px-4 py-2 bg-paper-3 hover:bg-paper-3/80 rounded-base border border-border text-sm font-medium transition focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-focus">
            Back to Chat
          </Link>
        </div>

        {error && (
          <div className="p-4 bg-red-900/20 border border-red-500/30 rounded-base text-red-400 text-sm">
            {error} - Are you sure you are an admin?
          </div>
        )}

        <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
          <div className="bg-paper-2 p-6 rounded-base border border-border">
            <h3 className="text-sm font-medium text-muted uppercase tracking-wider mb-2">Total Users</h3>
            <p className="text-3xl font-bold text-ink">{stats?.users || 0}</p>
          </div>
          <div className="bg-paper-2 p-6 rounded-base border border-border">
            <h3 className="text-sm font-medium text-muted uppercase tracking-wider mb-2">Total Sessions</h3>
            <p className="text-3xl font-bold text-ink">{stats?.sessions || 0}</p>
          </div>
          <div className="bg-paper-2 p-6 rounded-base border border-border">
            <h3 className="text-sm font-medium text-muted uppercase tracking-wider mb-2">Global Document Chunks</h3>
            <p className="text-3xl font-bold text-ink">{stats?.total_chunks || 0}</p>
          </div>
        </div>

        <div className="bg-paper-2 p-6 rounded-base border border-border shadow-[0_8px_30px_rgb(0,0,0,0.12)]">
          <div className="flex justify-between items-center mb-6">
            <h2 className="text-lg font-bold text-ink">Global Knowledge Base</h2>
            <div>
              <input
                type="file"
                ref={fileInputRef}
                onChange={handleUpload}
                className="hidden"
                accept=".txt,.pdf,.csv,.docx"
              />
              <button
                onClick={() => fileInputRef.current?.click()}
                disabled={isUploading}
                className="px-4 py-2 bg-accent hover:bg-accent/90 disabled:opacity-50 text-accent-ink rounded-base text-sm font-medium transition shadow-lg shadow-accent/20 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-focus"
              >
                {isUploading ? "Uploading..." : "Upload Global Document"}
              </button>
            </div>
          </div>

          {!stats || !stats.documents || stats.documents.length === 0 ? (
            <div className="text-center py-12 border border-dashed border-border rounded-base bg-paper text-muted">
              No global documents indexed yet.
            </div>
          ) : (
            <ul className="space-y-3">
              {stats.documents.map((doc, idx) => (
                <li key={idx} className="flex items-center justify-between p-4 rounded-base bg-paper border border-border hover:border-accent/50 transition">
                  <span className="font-medium text-ink">📄 {doc}</span>
                  <button
                    onClick={() => handleDelete(doc)}
                    className="text-muted hover:text-red-400 transition"
                  >
                    Remove
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>

        {/* ROLE REQUESTS */}
        <div className="bg-paper-2 p-6 rounded-base border border-border shadow-[0_8px_30px_rgb(0,0,0,0.12)]">
          <h2 className="text-lg font-bold text-ink mb-6">Pending Role Requests</h2>
          {requests.length === 0 ? (
            <div className="text-center py-6 border border-dashed border-border rounded-base bg-paper text-muted text-sm">
              No pending requests.
            </div>
          ) : (
            <ul className="space-y-3">
              {requests.map((req) => (
                <li key={req.id} className="flex items-center justify-between p-4 rounded-base bg-paper border border-border">
                  <div>
                    <div className="font-medium text-ink">User: {req.username}</div>
                    <div className="text-xs text-muted">Requested Role: <span className="text-accent font-semibold uppercase">{req.requested_role}</span></div>
                  </div>
                  <div className="flex gap-2">
                    <button onClick={() => handleApprove(req.id)} className="px-3 py-1 bg-green-900/20 hover:bg-green-900/40 text-green-400 border border-green-900/50 rounded-base transition text-sm">Approve</button>
                    <button onClick={() => handleReject(req.id)} className="px-3 py-1 bg-red-900/20 hover:bg-red-900/40 text-red-400 border border-red-900/50 rounded-base transition text-sm">Reject</button>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </div>

        {/* USER MANAGEMENT */}
        <div className="bg-paper-2 p-6 rounded-base border border-border shadow-[0_8px_30px_rgb(0,0,0,0.12)]">
          <h2 className="text-lg font-bold text-ink mb-6">User Management</h2>
          <div className="overflow-x-auto">
            <table className="w-full text-left border-collapse">
              <thead>
                <tr className="border-b border-border text-sm text-muted">
                  <th className="pb-3 font-medium">Username</th>
                  <th className="pb-3 font-medium">Joined</th>
                  <th className="pb-3 font-medium">Role</th>
                </tr>
              </thead>
              <tbody className="text-sm divide-y divide-border">
                {users.map(u => (
                  <tr key={u.id} className="hover:bg-paper/50">
                    <td className="py-3 text-ink font-medium">{u.username}</td>
                    <td className="py-3 text-muted">{new Date(u.created_at).toLocaleDateString()}</td>
                    <td className="py-3">
                      <select 
                        value={u.role} 
                        onChange={(e) => handleChangeRole(u.id, e.target.value)}
                        className="bg-paper border border-border text-ink rounded-base px-2 py-1 text-xs focus:outline-none focus:border-accent"
                      >
                        <option value="user">User</option>
                        <option value="editor">Editor</option>
                        <option value="admin">Admin</option>
                      </select>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

      </div>
    </div>
  );
}
