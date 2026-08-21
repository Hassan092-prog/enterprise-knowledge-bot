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
    <div className="min-h-screen bg-slate-900 text-slate-100 font-sans p-8">
      <div className="max-w-4xl mx-auto space-y-8">
        
        <div className="flex justify-between items-center bg-slate-800 p-6 rounded-2xl border border-slate-700 shadow-xl">
          <div>
            <h1 className="text-2xl font-bold bg-gradient-to-r from-indigo-400 to-cyan-400 bg-clip-text text-transparent">
              Admin Dashboard
            </h1>
            <p className="text-slate-400 text-sm mt-1">Manage global documents and view statistics</p>
          </div>
          <Link href="/" className="px-4 py-2 bg-slate-700 hover:bg-slate-600 rounded-lg text-sm font-medium transition">
            Back to Chat
          </Link>
        </div>

        {error && (
          <div className="p-4 bg-red-900/30 border border-red-500/50 rounded-lg text-red-400 text-sm">
            {error} - Are you sure you are an admin?
          </div>
        )}

        <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
          <div className="bg-slate-800 p-6 rounded-2xl border border-slate-700">
            <h3 className="text-sm font-medium text-slate-400 uppercase tracking-wider mb-2">Total Users</h3>
            <p className="text-3xl font-bold text-slate-100">{stats?.users || 0}</p>
          </div>
          <div className="bg-slate-800 p-6 rounded-2xl border border-slate-700">
            <h3 className="text-sm font-medium text-slate-400 uppercase tracking-wider mb-2">Total Sessions</h3>
            <p className="text-3xl font-bold text-slate-100">{stats?.sessions || 0}</p>
          </div>
          <div className="bg-slate-800 p-6 rounded-2xl border border-slate-700">
            <h3 className="text-sm font-medium text-slate-400 uppercase tracking-wider mb-2">Global Document Chunks</h3>
            <p className="text-3xl font-bold text-slate-100">{stats?.total_chunks || 0}</p>
          </div>
        </div>

        <div className="bg-slate-800 p-6 rounded-2xl border border-slate-700 shadow-xl">
          <div className="flex justify-between items-center mb-6">
            <h2 className="text-lg font-bold text-slate-200">Global Knowledge Base</h2>
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
                className="px-4 py-2 bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-white rounded-lg text-sm font-medium transition shadow-lg shadow-indigo-900/20"
              >
                {isUploading ? "Uploading..." : "Upload Global Document"}
              </button>
            </div>
          </div>

          {!stats || !stats.documents || stats.documents.length === 0 ? (
            <div className="text-center py-12 border border-dashed border-slate-700 rounded-xl bg-slate-900/20 text-slate-500">
              No global documents indexed yet.
            </div>
          ) : (
            <ul className="space-y-3">
              {stats.documents.map((doc, idx) => (
                <li key={idx} className="flex items-center justify-between p-4 rounded-xl bg-slate-900/50 border border-slate-700 hover:border-slate-600 transition">
                  <span className="font-medium text-slate-300">📄 {doc}</span>
                  <button
                    onClick={() => handleDelete(doc)}
                    className="text-slate-500 hover:text-red-400 transition"
                  >
                    Remove
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>

        {/* ROLE REQUESTS */}
        <div className="bg-slate-800 p-6 rounded-2xl border border-slate-700 shadow-xl">
          <h2 className="text-lg font-bold text-slate-200 mb-6">Pending Role Requests</h2>
          {requests.length === 0 ? (
            <div className="text-center py-6 border border-dashed border-slate-700 rounded-xl bg-slate-900/20 text-slate-500 text-sm">
              No pending requests.
            </div>
          ) : (
            <ul className="space-y-3">
              {requests.map((req) => (
                <li key={req.id} className="flex items-center justify-between p-4 rounded-xl bg-slate-900/50 border border-slate-700">
                  <div>
                    <div className="font-medium text-slate-200">User: {req.username}</div>
                    <div className="text-xs text-slate-400">Requested Role: <span className="text-cyan-400 font-semibold uppercase">{req.requested_role}</span></div>
                  </div>
                  <div className="flex gap-2">
                    <button onClick={() => handleApprove(req.id)} className="px-3 py-1 bg-green-600/20 hover:bg-green-600/40 text-green-400 border border-green-600/50 rounded transition text-sm">Approve</button>
                    <button onClick={() => handleReject(req.id)} className="px-3 py-1 bg-red-600/20 hover:bg-red-600/40 text-red-400 border border-red-600/50 rounded transition text-sm">Reject</button>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </div>

        {/* USER MANAGEMENT */}
        <div className="bg-slate-800 p-6 rounded-2xl border border-slate-700 shadow-xl">
          <h2 className="text-lg font-bold text-slate-200 mb-6">User Management</h2>
          <div className="overflow-x-auto">
            <table className="w-full text-left border-collapse">
              <thead>
                <tr className="border-b border-slate-700 text-sm text-slate-400">
                  <th className="pb-3 font-medium">Username</th>
                  <th className="pb-3 font-medium">Joined</th>
                  <th className="pb-3 font-medium">Role</th>
                </tr>
              </thead>
              <tbody className="text-sm divide-y divide-slate-700/50">
                {users.map(u => (
                  <tr key={u.id} className="hover:bg-slate-700/20">
                    <td className="py-3 text-slate-300 font-medium">{u.username}</td>
                    <td className="py-3 text-slate-500">{new Date(u.created_at).toLocaleDateString()}</td>
                    <td className="py-3">
                      <select 
                        value={u.role} 
                        onChange={(e) => handleChangeRole(u.id, e.target.value)}
                        className="bg-slate-900 border border-slate-600 text-slate-300 rounded px-2 py-1 text-xs focus:outline-none focus:border-indigo-500"
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
