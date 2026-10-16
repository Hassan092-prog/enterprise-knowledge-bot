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
        setError("Failed to load statistics");
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
    <div className="min-h-screen bg-paper text-ink p-4 sm:p-8">
      <div className="max-w-5xl mx-auto space-y-6">
        
        {/* Navigation / Header */}
        <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4 bg-paper-2 p-5 rounded-card border border-rule">
          <div>
            <div className="flex items-center gap-2 mb-1">
              <span className="w-2 h-2 rounded-full bg-accent" />
              <span className="font-mono text-xs uppercase tracking-wider text-muted font-medium">
                Admin Console
              </span>
            </div>
            <h1 className="text-xl font-display font-semibold text-ink tracking-tight">
              System Telemetry & Access Control
            </h1>
          </div>
          <Link
            href="/"
            className="px-3.5 py-1.5 bg-paper hover:bg-paper-3 rounded-base border border-rule text-xs font-mono uppercase tracking-wider text-ink transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-focus cursor-pointer"
          >
            ← Return to Workspace
          </Link>
        </div>

        {error && (
          <div className="p-3.5 bg-ruby-subtle border border-ruby/30 rounded-base text-ruby text-xs font-mono">
            [ERR] {error} — Administrator privileges required.
          </div>
        )}

        {/* METRICS ROW */}
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
          <div className="bg-paper-2 p-5 rounded-card border border-rule">
            <span className="font-mono text-[11px] uppercase tracking-wider text-muted block mb-1">
              Registered Identities
            </span>
            <p className="text-2xl sm:text-3xl font-display font-semibold text-ink">
              {stats?.users || 0}
            </p>
          </div>
          <div className="bg-paper-2 p-5 rounded-card border border-rule">
            <span className="font-mono text-[11px] uppercase tracking-wider text-muted block mb-1">
              Active Sessions
            </span>
            <p className="text-2xl sm:text-3xl font-display font-semibold text-ink">
              {stats?.sessions || 0}
            </p>
          </div>
          <div className="bg-paper-2 p-5 rounded-card border border-rule">
            <span className="font-mono text-[11px] uppercase tracking-wider text-muted block mb-1">
              Vector Store Chunks (ChromaDB)
            </span>
            <p className="text-2xl sm:text-3xl font-display font-semibold text-ink">
              {stats?.total_chunks || 0}
            </p>
          </div>
        </div>

        {/* GLOBAL CORPUS MANAGEMENT */}
        <div className="bg-paper-2 p-5 sm:p-6 rounded-card border border-rule">
          <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4 mb-5 pb-4 border-b border-rule">
            <div>
              <h2 className="text-base font-display font-semibold text-ink">
                Global Knowledge Corpus
              </h2>
              <p className="text-xs text-muted mt-0.5">
                Documents available enterprise-wide for hybrid retrieval and semantic indexing.
              </p>
            </div>
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
                className="px-3.5 py-2 bg-accent hover:bg-accent-hover text-accent-ink rounded-base text-xs font-mono uppercase tracking-wider font-semibold transition-colors disabled:opacity-50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-focus cursor-pointer"
              >
                {isUploading ? "Indexing..." : "+ Ingest Global Document"}
              </button>
            </div>
          </div>

          {!stats || !stats.documents || stats.documents.length === 0 ? (
            <div className="text-center py-8 border border-dashed border-rule rounded-base bg-paper text-muted text-xs font-mono">
              [NO_GLOBAL_DOCUMENTS_INDEXED]
            </div>
          ) : (
            <ul className="space-y-2">
              {stats.documents.map((doc, idx) => (
                <li
                  key={idx}
                  className="flex items-center justify-between p-3 rounded-base bg-paper border border-rule hover:border-rule-focus transition-colors"
                >
                  <div className="flex items-center gap-2 overflow-hidden">
                    <span className="font-mono text-[11px] px-1.5 py-0.5 bg-paper-2 rounded border border-rule text-muted">
                      {doc.split('.').pop()?.toUpperCase() || 'FILE'}
                    </span>
                    <span className="text-sm font-medium text-ink truncate" title={doc}>
                      {doc}
                    </span>
                  </div>
                  <button
                    onClick={() => handleDelete(doc)}
                    className="text-xs font-mono text-muted hover:text-ruby px-2 py-1 rounded transition-colors"
                  >
                    Delete
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>

        {/* ROLE APPROVAL REQUESTS */}
        <div className="bg-paper-2 p-5 sm:p-6 rounded-card border border-rule">
          <div className="mb-4 pb-3 border-b border-rule">
            <h2 className="text-base font-display font-semibold text-ink">
              Privilege Escalation Requests
            </h2>
            <p className="text-xs text-muted mt-0.5">
              Pending authorization requests for editor and administrator roles.
            </p>
          </div>

          {requests.length === 0 ? (
            <div className="text-center py-6 border border-dashed border-rule rounded-base bg-paper text-muted text-xs font-mono">
              [NO_PENDING_ROLE_REQUESTS]
            </div>
          ) : (
            <ul className="space-y-2.5">
              {requests.map((req) => (
                <li
                  key={req.id}
                  className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3 p-3.5 rounded-base bg-paper border border-rule"
                >
                  <div>
                    <div className="text-sm font-medium text-ink">{req.username}</div>
                    <div className="font-mono text-xs text-muted mt-0.5">
                      Requested Role:{" "}
                      <span className="text-accent uppercase font-semibold">
                        {req.requested_role}
                      </span>
                    </div>
                  </div>
                  <div className="flex gap-2">
                    <button
                      onClick={() => handleApprove(req.id)}
                      className="px-3 py-1 bg-emerald-subtle hover:bg-emerald/20 text-emerald border border-emerald/30 rounded-base text-xs font-mono uppercase tracking-wider transition-colors cursor-pointer"
                    >
                      Approve
                    </button>
                    <button
                      onClick={() => handleReject(req.id)}
                      className="px-3 py-1 bg-ruby-subtle hover:bg-ruby/20 text-ruby border border-ruby/30 rounded-base text-xs font-mono uppercase tracking-wider transition-colors cursor-pointer"
                    >
                      Reject
                    </button>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </div>

        {/* IDENTITY ROSTER MANAGEMENT */}
        <div className="bg-paper-2 p-5 sm:p-6 rounded-card border border-rule">
          <div className="mb-4 pb-3 border-b border-rule">
            <h2 className="text-base font-display font-semibold text-ink">
              Identity Roster
            </h2>
            <p className="text-xs text-muted mt-0.5">
              Manage permission tier assignments across authenticated users.
            </p>
          </div>

          <div className="overflow-x-auto border border-rule rounded-base bg-paper">
            <table className="w-full text-left border-collapse">
              <thead>
                <tr className="border-b border-rule bg-paper-3 text-xs font-mono uppercase tracking-wider text-ink">
                  <th className="p-3 font-semibold">Identity</th>
                  <th className="p-3 font-semibold">Registered</th>
                  <th className="p-3 font-semibold">Assigned Role</th>
                </tr>
              </thead>
              <tbody className="text-xs divide-y divide-rule font-body">
                {users.map(u => (
                  <tr key={u.id} className="hover:bg-paper-2 transition-colors">
                    <td className="p-3 font-medium text-ink">{u.username}</td>
                    <td className="p-3 font-mono text-muted">
                      {new Date(u.created_at).toLocaleDateString()}
                    </td>
                    <td className="p-3">
                      <select 
                        value={u.role} 
                        onChange={(e) => handleChangeRole(u.id, e.target.value)}
                        className="bg-paper-2 border border-rule text-ink rounded-base px-2.5 py-1 text-xs font-mono focus:outline-none focus:border-accent cursor-pointer"
                      >
                        <option value="user">USER</option>
                        <option value="editor">EDITOR</option>
                        <option value="admin">ADMIN</option>
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

