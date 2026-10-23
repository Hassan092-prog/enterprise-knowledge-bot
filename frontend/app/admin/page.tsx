"use client";

import { useState, useRef, useEffect, useCallback } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://192.168.1.92:8000";

type Stats = {
  tenant_id: number;
  tenant_name: string;
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
  is_platform_admin: boolean;
  created_at: string;
};

type ActivityItem = {
  id: number;
  username: string;
  action: string;
  category: string;
  description: string;
  details?: string;
  timestamp: string;
};

type PendingTransfer = {
  id: number;
  from_user_id: number;
  from_username: string;
  to_user_id: number;
  to_username: string;
  created_at: string;
  expires_at: string;
  is_recipient: boolean;
};

export default function AdminDashboard() {
  const [activeTab, setActiveTab] = useState<"roster" | "corpus" | "activity" | "settings">("roster");
  const [stats, setStats] = useState<Stats | null>(null);
  const [requests, setRequests] = useState<RoleRequest[]>([]);
  const [users, setUsers] = useState<UserData[]>([]);
  const [activities, setActivities] = useState<ActivityItem[]>([]);
  const [activityCategory, setActivityCategory] = useState<string>("");
  const [joinCode, setJoinCode] = useState<string>("");
  const [isKeyCopied, setIsKeyCopied] = useState<boolean>(false);
  const [pendingTransfers, setPendingTransfers] = useState<PendingTransfer[]>([]);
  const [transferTargetUserId, setTransferTargetUserId] = useState<number | "">("");

  const [currentUserRole, setCurrentUserRole] = useState<string>("");
  const [isPlatformAdmin, setIsPlatformAdmin] = useState<boolean>(false);
  const [currentUsername, setCurrentUsername] = useState<string>("");

  const [isUploading, setIsUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);

  const fileInputRef = useRef<HTMLInputElement>(null);
  const router = useRouter();

  const authFetch = useCallback(async (url: string, options: RequestInit = {}) => {
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
    if (res.status === 401) {
      localStorage.removeItem("token");
      router.push("/login");
      throw new Error("Session expired. Please log in again.");
    }
    return res;
  }, [router]);

  const fetchStatsAndData = useCallback(async () => {
    try {
      setError(null);
      // Fetch me
      const meRes = await authFetch(`${API_URL}/auth/me`);
      if (meRes.ok) {
        const me = await meRes.json();
        if (me.access_token) {
          localStorage.setItem("token", me.access_token);
        }
        setCurrentUserRole(me.role);
        if (me.role) localStorage.setItem("role", me.role);
        setIsPlatformAdmin(Boolean(me.is_platform_admin));
        setCurrentUsername(me.username);
      }

      // Fetch Stats
      const res = await authFetch(`${API_URL}/admin/stats`);
      if (res.ok) {
        const data = await res.json();
        setStats(data);
      } else {
        const err = await res.json();
        throw new Error(err.detail || "Access denied: Admin role required");
      }

      // Fetch Requests
      const reqRes = await authFetch(`${API_URL}/admin/requests`);
      if (reqRes.ok) {
        setRequests(await reqRes.json());
      }

      // Fetch Users
      const usersRes = await authFetch(`${API_URL}/admin/users`);
      if (usersRes.ok) {
        setUsers(await usersRes.json());
      }

      // Fetch Join Code
      const jcRes = await authFetch(`${API_URL}/admin/join_code`);
      if (jcRes.ok) {
        const jcData = await jcRes.json();
        setJoinCode(jcData.join_code || "");
      }

      // Fetch Transfers
      const trRes = await authFetch(`${API_URL}/admin/pending_transfers`);
      if (trRes.ok) {
        setPendingTransfers(await trRes.json());
      }
    } catch (err: unknown) {
      if (err instanceof Error) {
        setError(err.message);
      } else {
        setError("Failed to load administration data");
      }
    }
  }, [authFetch]);

  const fetchActivity = useCallback(async (categoryFilter = "") => {
    try {
      const url = categoryFilter
        ? `${API_URL}/admin/activity?category=${categoryFilter}&limit=100`
        : `${API_URL}/admin/activity?limit=100`;
      const res = await authFetch(url);
      if (res.ok) {
        setActivities(await res.json());
      }
    } catch (err) {
      console.error("Activity load error:", err);
    }
  }, [authFetch]);

  useEffect(() => {
    fetchStatsAndData();
  }, [fetchStatsAndData]);

  useEffect(() => {
    if (activeTab === "activity") {
      fetchActivity(activityCategory);
    }
  }, [activeTab, activityCategory, fetchActivity]);

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
        setSuccessMsg(`Document '${file.name}' successfully ingested into company corpus.`);
        await fetchStatsAndData();
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
    if (!confirm(`Purge document '${filename}' and all its embeddings from your company corpus?`)) return;
    try {
      const res = await authFetch(`${API_URL}/admin/documents_global/${filename}`, {
        method: "DELETE",
      });
      if (res.ok) {
        setSuccessMsg(`Document '${filename}' deleted.`);
        await fetchStatsAndData();
      }
    } catch (error) {
      console.error("Delete error:", error);
    }
  };

  const handleApprove = async (id: number) => {
    try {
      const res = await authFetch(`${API_URL}/admin/requests/${id}/approve`, { method: "POST" });
      if (res.ok) await fetchStatsAndData();
    } catch (err) {
      console.error(err);
    }
  };

  const handleReject = async (id: number) => {
    try {
      const res = await authFetch(`${API_URL}/admin/requests/${id}/reject`, { method: "POST" });
      if (res.ok) await fetchStatsAndData();
    } catch (err) {
      console.error(err);
    }
  };

  const handleChangeRole = async (userId: number, role: string) => {
    try {
      const res = await authFetch(`${API_URL}/admin/users/${userId}/role`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ role }),
      });
      if (res.ok) {
        setSuccessMsg("Role updated successfully.");
        await fetchStatsAndData();
      } else {
        const err = await res.json();
        alert(err.detail || "Failed to change role");
      }
    } catch (err) {
      console.error(err);
    }
  };

  const handleRemoveUser = async (userId: number, targetUsername: string) => {
    if (!confirm(`Are you sure you want to permanently remove member '${targetUsername}' from ${stats?.tenant_name || "the organization"}?`)) return;
    try {
      const res = await authFetch(`${API_URL}/admin/users/${userId}`, {
        method: "DELETE",
      });
      if (res.ok) {
        setSuccessMsg(`Member '${targetUsername}' removed from organization.`);
        await fetchStatsAndData();
      } else {
        const err = await res.json();
        alert(err.detail || "Failed to remove member");
      }
    } catch (err) {
      console.error(err);
      alert("Failed to connect to backend");
    }
  };

  const handleRegenerateJoinCode = async () => {
    if (!confirm("Regenerate join code? Any previous join codes will cease to work.")) return;
    try {
      const res = await authFetch(`${API_URL}/admin/regenerate_join_code`, { method: "POST" });
      if (res.ok) {
        const data = await res.json();
        setJoinCode(data.join_code);
        setSuccessMsg("Organization join code regenerated.");
      }
    } catch (err) {
      console.error(err);
    }
  };

  const handleCopyJoinCode = () => {
    if (!joinCode) return;

    const copyWithFallback = () => {
      try {
        const textarea = document.createElement("textarea");
        textarea.value = joinCode;
        textarea.style.position = "fixed";
        textarea.style.left = "-9999px";
        textarea.style.top = "-9999px";
        document.body.appendChild(textarea);
        textarea.focus();
        textarea.select();
        const successful = document.execCommand("copy");
        document.body.removeChild(textarea);
        if (successful) {
          setIsKeyCopied(true);
          setSuccessMsg("Join code copied to clipboard!");
          setTimeout(() => setIsKeyCopied(false), 2500);
        } else {
          prompt("Copy join code manually (Ctrl+C, Enter):", joinCode);
        }
      } catch {
        prompt("Copy join code manually (Ctrl+C, Enter):", joinCode);
      }
    };

    if (navigator.clipboard && window.isSecureContext) {
      navigator.clipboard.writeText(joinCode).then(() => {
        setIsKeyCopied(true);
        setSuccessMsg("Join code copied to clipboard!");
        setTimeout(() => setIsKeyCopied(false), 2500);
      }).catch(() => {
        copyWithFallback();
      });
    } else {
      copyWithFallback();
    }
  };

  const handleInitiateTransfer = async () => {
    if (!transferTargetUserId) {
      alert("Please select a target user.");
      return;
    }
    if (!confirm("Initiate ownership transfer? The selected user must accept within 24 hours to finalize.")) return;

    try {
      const res = await authFetch(`${API_URL}/admin/transfer_superadmin`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ to_user_id: Number(transferTargetUserId) }),
      });

      if (res.ok) {
        setSuccessMsg("SuperAdmin ownership transfer offer sent.");
        setTransferTargetUserId("");
        await fetchStatsAndData();
      } else {
        const err = await res.json();
        alert(err.detail || "Failed to initiate transfer");
      }
    } catch (err) {
      console.error(err);
    }
  };

  const handleAcceptTransfer = async (transferId: number) => {
    try {
      const res = await authFetch(`${API_URL}/admin/accept_transfer/${transferId}`, { method: "POST" });
      if (res.ok) {
        alert("Congratulations! You are now the SuperAdmin of this organization.");
        await fetchStatsAndData();
      } else {
        const err = await res.json();
        alert(err.detail || "Failed to accept transfer");
      }
    } catch (err) {
      console.error(err);
    }
  };

  const handleCancelTransfer = async (transferId: number) => {
    try {
      const res = await authFetch(`${API_URL}/admin/cancel_transfer/${transferId}`, { method: "POST" });
      if (res.ok) {
        setSuccessMsg("Ownership transfer offer cancelled.");
        await fetchStatsAndData();
      } else {
        const err = await res.json();
        alert(err.detail || "Failed to cancel transfer");
      }
    } catch (err) {
      console.error(err);
    }
  };

  const handleRejectTransfer = async (transferId: number) => {
    try {
      const res = await authFetch(`${API_URL}/admin/reject_transfer/${transferId}`, { method: "POST" });
      if (res.ok) {
        setSuccessMsg("Ownership transfer declined.");
        await fetchStatsAndData();
      } else {
        const err = await res.json();
        alert(err.detail || "Failed to decline transfer");
      }
    } catch (err) {
      console.error(err);
    }
  };

  return (
    <div className="min-h-screen bg-paper text-ink p-4 sm:p-8">
      <div className="max-w-5xl mx-auto space-y-6">
        
        {/* Navigation / Header */}
        <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4 bg-paper-2 p-5 rounded-card border border-rule">
          <div>
            <div className="flex items-center gap-2 mb-1">
              <span className="w-2 h-2 rounded-full bg-accent animate-pulse" />
              <span className="font-mono text-xs uppercase tracking-wider text-muted font-medium">
                {stats?.tenant_name || "Organization"} // Tenant Console
              </span>
              <span className="font-mono text-[10px] px-2 py-0.5 rounded border border-accent/40 bg-accent-subtle text-accent font-semibold uppercase">
                {currentUserRole === "superadmin" ? "👑 SuperAdmin" : "🛡️ Admin"}
              </span>
            </div>
            <h1 className="text-xl font-display font-semibold text-ink tracking-tight">
              Organization Governance & Audit Console
            </h1>
          </div>
          <div className="flex items-center gap-2 flex-wrap">
            {isPlatformAdmin && (
              <Link
                href="/platform-admin"
                className="px-3.5 py-1.5 bg-paper hover:bg-paper-3 rounded-base border border-accent text-xs font-mono uppercase tracking-wider text-accent font-semibold transition-colors"
              >
                🌐 Platform Control Plane →
              </Link>
            )}
            <Link
              href="/"
              className="px-3.5 py-1.5 bg-paper hover:bg-paper-3 rounded-base border border-rule text-xs font-mono uppercase tracking-wider text-ink transition-colors"
            >
              ← Chat Workspace
            </Link>
          </div>
        </div>

        {/* Incoming Transfer Alert */}
        {pendingTransfers.some((t) => t.is_recipient) && (
          <div className="p-4 bg-amber-500/10 border border-amber-500/40 rounded-card flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3">
            <div>
              <span className="font-mono text-xs uppercase font-bold text-amber-500 block mb-0.5">
                👑 SuperAdmin Ownership Offer Received
              </span>
              <p className="text-xs text-ink">
                You have been offered the primary ownership (SuperAdmin) of this organization. Accepting will grant you exclusive governance authority.
              </p>
            </div>
            {pendingTransfers
              .filter((t) => t.is_recipient)
              .map((t) => (
                <button
                  key={t.id}
                  onClick={() => handleAcceptTransfer(t.id)}
                  className="px-4 py-2 bg-amber-500 hover:bg-amber-600 text-black font-mono text-xs uppercase tracking-wider font-semibold rounded-base cursor-pointer"
                >
                  Accept SuperAdmin Role →
                </button>
              ))}
          </div>
        )}

        {error && (
          <div className="p-3.5 bg-ruby-subtle border border-ruby/30 rounded-base text-ruby text-xs font-mono">
            [ERR] {error}
          </div>
        )}

        {successMsg && (
          <div className="p-3.5 bg-emerald-subtle border border-emerald/30 rounded-base text-emerald text-xs font-mono flex justify-between items-center">
            <span>[OK] {successMsg}</span>
            <button onClick={() => setSuccessMsg(null)} className="text-muted hover:text-ink">✕</button>
          </div>
        )}

        {/* Metrics Row */}
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
          <div className="bg-paper-2 p-5 rounded-card border border-rule">
            <span className="font-mono text-[11px] uppercase tracking-wider text-muted block mb-1">
              Organization Members
            </span>
            <p className="text-2xl sm:text-3xl font-display font-semibold text-ink">
              {stats?.users || 0}
            </p>
          </div>
          <div className="bg-paper-2 p-5 rounded-card border border-rule">
            <span className="font-mono text-[11px] uppercase tracking-wider text-muted block mb-1">
              Active Member Sessions
            </span>
            <p className="text-2xl sm:text-3xl font-display font-semibold text-ink">
              {stats?.sessions || 0}
            </p>
          </div>
          <div className="bg-paper-2 p-5 rounded-card border border-rule">
            <span className="font-mono text-[11px] uppercase tracking-wider text-muted block mb-1">
              Company Corpus Chunks
            </span>
            <p className="text-2xl sm:text-3xl font-display font-semibold text-ink">
              {stats?.total_chunks || 0}
            </p>
          </div>
        </div>

        {/* INCOMING OWNERSHIP TRANSFER HANDSHAKE BANNER */}
        {pendingTransfers.filter((t) => t.is_recipient).map((t) => (
          <div key={t.id} className="p-4 rounded-card bg-amber-500/10 border border-amber-500/40 flex flex-col sm:flex-row justify-between items-start sm:items-center gap-3">
            <div>
              <div className="flex items-center gap-2">
                <span className="w-2 h-2 rounded-full bg-amber-500 animate-pulse" />
                <span className="font-mono text-xs font-bold uppercase tracking-wider text-amber-500">
                  SuperAdmin Ownership Transfer Offer
                </span>
              </div>
              <p className="text-xs text-ink-secondary mt-1">
                <strong>{t.from_username}</strong> has offered to permanently delegate SuperAdmin ownership of <strong>{stats?.tenant_name}</strong> to your account.
              </p>
            </div>
            <div className="flex items-center gap-2">
              <button
                onClick={() => handleAcceptTransfer(t.id)}
                className="px-4 py-2 bg-emerald-subtle hover:bg-emerald/20 text-emerald border border-emerald/40 text-xs font-mono uppercase tracking-wider font-semibold rounded-base cursor-pointer"
              >
                Accept Ownership Transfer →
              </button>
              <button
                onClick={() => handleRejectTransfer(t.id)}
                className="px-3 py-2 bg-ruby-subtle hover:bg-ruby/20 text-ruby border border-ruby/40 text-xs font-mono uppercase tracking-wider rounded-base cursor-pointer"
              >
                Decline
              </button>
            </div>
          </div>
        ))}

        {/* TABS NAVIGATION */}
        <div className="flex border-b border-rule space-x-2">
          <button
            onClick={() => setActiveTab("roster")}
            className={`py-2 px-4 text-xs font-mono uppercase tracking-wider border-b-2 font-semibold transition-colors cursor-pointer ${
              activeTab === "roster"
                ? "border-accent text-ink"
                : "border-transparent text-muted hover:text-ink"
            }`}
          >
            Members & Roles ({users.length})
          </button>
          <button
            onClick={() => setActiveTab("corpus")}
            className={`py-2 px-4 text-xs font-mono uppercase tracking-wider border-b-2 font-semibold transition-colors cursor-pointer ${
              activeTab === "corpus"
                ? "border-accent text-ink"
                : "border-transparent text-muted hover:text-ink"
            }`}
          >
            Company Corpus ({stats?.documents?.length || 0})
          </button>
          <button
            onClick={() => setActiveTab("activity")}
            className={`py-2 px-4 text-xs font-mono uppercase tracking-wider border-b-2 font-semibold transition-colors cursor-pointer ${
              activeTab === "activity"
                ? "border-accent text-ink"
                : "border-transparent text-muted hover:text-ink"
            }`}
          >
            Activity & Audit Log
          </button>
          <button
            onClick={() => setActiveTab("settings")}
            className={`py-2 px-4 text-xs font-mono uppercase tracking-wider border-b-2 font-semibold transition-colors cursor-pointer ${
              activeTab === "settings"
                ? "border-accent text-ink"
                : "border-transparent text-muted hover:text-ink"
            }`}
          >
            Organization Settings
          </button>
        </div>

        {/* TAB 1: MEMBERS & ROLES */}
        {activeTab === "roster" && (
          <div className="space-y-6">
            {/* ROLE REQUESTS */}
            <div className="bg-paper-2 p-5 sm:p-6 rounded-card border border-rule">
              <div className="mb-4 pb-3 border-b border-rule">
                <h2 className="text-base font-display font-semibold text-ink">
                  Privilege Escalation Requests
                </h2>
                <p className="text-xs text-muted mt-0.5">
                  Pending authorization requests from organization members.
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

            {/* IDENTITY ROSTER TABLE */}
            <div className="bg-paper-2 p-5 sm:p-6 rounded-card border border-rule">
              <div className="mb-4 pb-3 border-b border-rule">
                <h2 className="text-base font-display font-semibold text-ink">
                  Member Directory & Roles
                </h2>
                <p className="text-xs text-muted mt-0.5">
                  Manage permissions across organization accounts.
                </p>
              </div>

              <div className="overflow-x-auto border border-rule rounded-base bg-paper">
                <table className="w-full text-left border-collapse">
                  <thead>
                    <tr className="border-b border-rule bg-paper-3 text-xs font-mono uppercase tracking-wider text-ink">
                      <th className="p-3 font-semibold">Member</th>
                      <th className="p-3 font-semibold">Registered</th>
                      <th className="p-3 font-semibold">Assigned Role</th>
                      <th className="p-3 font-semibold text-right">Actions</th>
                    </tr>
                  </thead>
                  <tbody className="text-xs divide-y divide-rule font-body">
                    {users.map((u) => {
                      const isSelf = u.username === currentUsername;
                      const isSuperadmin = u.role === "superadmin";
                      const canRemove = !isSelf && !isSuperadmin && (currentUserRole === "superadmin" || (currentUserRole === "admin" && u.role !== "admin"));

                      return (
                        <tr key={u.id} className="hover:bg-paper-2 transition-colors">
                          <td className="p-3 font-medium text-ink">
                            <div className="flex items-center gap-2">
                              <span>{u.username}</span>
                              {isSelf && (
                                <span className="font-mono text-[10px] px-1.5 py-0.2 rounded border border-rule text-muted">
                                  You
                                </span>
                              )}
                              {isSuperadmin && (
                                <span className="text-[11px] text-amber-500 font-mono">
                                  👑 SuperAdmin
                                </span>
                              )}
                            </div>
                          </td>
                          <td className="p-3 font-mono text-muted">
                            {new Date(u.created_at).toLocaleDateString()}
                          </td>
                          <td className="p-3">
                            {isSuperadmin ? (
                              <span className="font-mono text-xs font-bold text-amber-500">
                                OWNER (TRANSFER ONLY)
                              </span>
                            ) : (
                              <select
                                value={u.role}
                                disabled={isSelf || (currentUserRole !== "superadmin" && u.role === "admin")}
                                onChange={(e) => handleChangeRole(u.id, e.target.value)}
                                className="bg-paper-2 border border-rule text-ink rounded-base px-2.5 py-1 text-xs font-mono focus:outline-none focus:border-accent cursor-pointer disabled:opacity-50"
                              >
                                <option value="user">USER (MEMBER)</option>
                                <option value="editor">EDITOR</option>
                                {currentUserRole === "superadmin" && <option value="admin">ADMIN</option>}
                              </select>
                            )}
                          </td>
                          <td className="p-3 text-right">
                            {canRemove ? (
                              <button
                                onClick={() => handleRemoveUser(u.id, u.username)}
                                className="px-2.5 py-1 text-[11px] font-mono uppercase tracking-wider text-ruby hover:bg-ruby-subtle border border-ruby/30 hover:border-ruby/60 rounded-base transition-colors cursor-pointer"
                                title={`Remove ${u.username} from organization`}
                              >
                                Remove
                              </button>
                            ) : (
                              <span className="text-muted font-mono text-[11px]">—</span>
                            )}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        )}

        {/* TAB 2: COMPANY CORPUS */}
        {activeTab === "corpus" && (
          <div className="bg-paper-2 p-5 sm:p-6 rounded-card border border-rule">
            <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4 mb-5 pb-4 border-b border-rule">
              <div>
                <h2 className="text-base font-display font-semibold text-ink">
                  Company Knowledge Corpus
                </h2>
                <p className="text-xs text-muted mt-0.5">
                  Documents accessible to all members within this tenant organization.
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
                  className="px-3.5 py-2 bg-accent hover:bg-accent-hover text-accent-ink rounded-base text-xs font-mono uppercase tracking-wider font-semibold transition-colors disabled:opacity-50 cursor-pointer"
                >
                  {isUploading ? "Indexing..." : "+ Ingest Company Document"}
                </button>
              </div>
            </div>

            {!stats || !stats.documents || stats.documents.length === 0 ? (
              <div className="text-center py-8 border border-dashed border-rule rounded-base bg-paper text-muted text-xs font-mono">
                [NO_COMPANY_CORPUS_DOCUMENTS_INDEXED]
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
                        {doc.split(".").pop()?.toUpperCase() || "FILE"}
                      </span>
                      <span className="text-sm font-medium text-ink truncate" title={doc}>
                        {doc}
                      </span>
                    </div>
                    <button
                      onClick={() => handleDelete(doc)}
                      className="text-xs font-mono text-muted hover:text-ruby px-2 py-1 rounded transition-colors cursor-pointer"
                    >
                      Delete
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}

        {/* TAB 3: ACTIVITY & AUDIT LOG */}
        {activeTab === "activity" && (
          <div className="bg-paper-2 p-5 sm:p-6 rounded-card border border-rule space-y-4">
            <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4 pb-3 border-b border-rule">
              <div>
                <h2 className="text-base font-display font-semibold text-ink">
                  Tenant Activity & Audit Stream
                </h2>
                <p className="text-xs text-muted mt-0.5">
                  Real-time telemetry of query executions, corpus ingestion, and governance events.
                </p>
              </div>
              <div className="flex items-center gap-2">
                <span className="text-xs font-mono text-muted uppercase">Category:</span>
                <select
                  value={activityCategory}
                  onChange={(e) => setActivityCategory(e.target.value)}
                  className="bg-paper border border-rule text-ink text-xs font-mono rounded-base px-2 py-1 focus:outline-none focus:border-accent"
                >
                  <option value="">ALL</option>
                  <option value="QUERY">QUERY</option>
                  <option value="KNOWLEDGE">KNOWLEDGE</option>
                  <option value="GOVERNANCE">GOVERNANCE</option>
                  <option value="AUTH">AUTH</option>
                </select>
                <button
                  onClick={() => fetchActivity(activityCategory)}
                  className="px-2 py-1 bg-paper border border-rule hover:bg-paper-3 text-xs font-mono text-ink rounded-base"
                >
                  ↻ Refresh
                </button>
              </div>
            </div>

            {activities.length === 0 ? (
              <div className="text-center py-8 border border-dashed border-rule rounded-base bg-paper text-muted text-xs font-mono">
                [NO_ACTIVITY_RECORDED]
              </div>
            ) : (
              <div className="overflow-x-auto border border-rule rounded-base bg-paper">
                <table className="w-full text-left border-collapse">
                  <thead>
                    <tr className="border-b border-rule bg-paper-3 text-[11px] font-mono uppercase tracking-wider text-ink">
                      <th className="p-2.5">Time (UTC)</th>
                      <th className="p-2.5">User</th>
                      <th className="p-2.5">Category</th>
                      <th className="p-2.5">Event</th>
                    </tr>
                  </thead>
                  <tbody className="text-xs divide-y divide-rule font-mono">
                    {activities.map((a) => (
                      <tr key={a.id} className="hover:bg-paper-2 transition-colors">
                        <td className="p-2.5 text-muted whitespace-nowrap">
                          {new Date(a.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })}
                        </td>
                        <td className="p-2.5 font-semibold text-ink whitespace-nowrap">
                          {a.username}
                        </td>
                        <td className="p-2.5">
                          <span className={`px-1.5 py-0.5 rounded text-[10px] uppercase font-bold ${
                            a.category === "QUERY" ? "bg-blue-500/10 text-blue-400 border border-blue-500/30" :
                            a.category === "KNOWLEDGE" ? "bg-emerald-500/10 text-emerald-400 border border-emerald-500/30" :
                            a.category === "GOVERNANCE" ? "bg-amber-500/10 text-amber-400 border border-amber-500/30" :
                            "bg-purple-500/10 text-purple-400 border border-purple-500/30"
                          }`}>
                            {a.category}
                          </span>
                        </td>
                        <td className="p-2.5 text-ink font-body">
                          {a.description}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        )}

        {/* TAB 4: SETTINGS */}
        {activeTab === "settings" && (
          <div className="space-y-6">
            {/* JOIN CODE */}
            <div className="bg-paper-2 p-5 sm:p-6 rounded-card border border-rule">
              <h2 className="text-base font-display font-semibold text-ink mb-1">
                Organization Join Code
              </h2>
              <p className="text-xs text-muted mb-4">
                Share this secret key with colleagues to authorize their registration into your tenant.
              </p>

              <div className="flex flex-col sm:flex-row items-stretch sm:items-center gap-3">
                <div className="relative flex-1">
                  <input
                    type="text"
                    readOnly
                    value={joinCode || "Generating..."}
                    onClick={(e) => (e.target as HTMLInputElement).select()}
                    className="w-full p-3 bg-paper border border-rule rounded-base font-mono text-base font-bold tracking-widest text-accent text-center sm:text-left select-all cursor-pointer focus:outline-none focus:border-accent"
                    title="Click to select all text"
                  />
                </div>
                <button
                  onClick={handleCopyJoinCode}
                  className={`px-4 py-2 border text-xs font-mono uppercase tracking-wider rounded-base transition-colors cursor-pointer flex items-center justify-center gap-1.5 ${
                    isKeyCopied
                      ? "bg-emerald-subtle border-emerald text-emerald font-bold"
                      : "bg-paper hover:bg-paper-3 border-rule text-ink"
                  }`}
                >
                  {isKeyCopied ? "✓ Key Copied" : "Copy Key"}
                </button>
                {currentUserRole === "superadmin" && (
                  <button
                    onClick={handleRegenerateJoinCode}
                    className="px-4 py-2 bg-ruby-subtle hover:bg-ruby/20 border border-ruby/30 text-xs font-mono uppercase tracking-wider text-ruby rounded-base cursor-pointer"
                  >
                    Regenerate Key
                  </button>
                )}
              </div>
            </div>

            {/* SUPERADMIN TRANSFER (SUPERADMIN ONLY) */}
            {currentUserRole === "superadmin" && (
              <div className="bg-paper-2 p-5 sm:p-6 rounded-card border border-rule">
                <h2 className="text-base font-display font-semibold text-ink mb-1">
                  SuperAdmin Ownership Transfer
                </h2>
                <p className="text-xs text-muted mb-4">
                  Permanently delegate your SuperAdmin status to another verified member. The recipient must accept within 24 hours.
                </p>

                <div className="flex flex-col sm:flex-row items-stretch sm:items-center gap-3">
                  <select
                    value={transferTargetUserId}
                    onChange={(e) => setTransferTargetUserId(Number(e.target.value) || "")}
                    className="bg-paper border border-rule text-ink text-xs font-body rounded-base px-3 py-2 flex-1 focus:outline-none focus:border-accent"
                  >
                    <option value="">Select recipient member...</option>
                    {users
                      .filter((u) => u.username !== currentUsername)
                      .map((u) => (
                        <option key={u.id} value={u.id}>
                          {u.username} ({u.role.toUpperCase()})
                        </option>
                      ))}
                  </select>
                  <button
                    onClick={handleInitiateTransfer}
                    className="px-4 py-2 bg-accent hover:bg-accent-hover text-accent-ink text-xs font-mono uppercase tracking-wider font-semibold rounded-base cursor-pointer"
                  >
                    Initiate Transfer →
                  </button>
                </div>

                {/* Pending outgoing transfer */}
                {pendingTransfers.filter((t) => !t.is_recipient).map((t) => (
                  <div key={t.id} className="mt-4 p-3 bg-paper border border-rule rounded-base text-xs font-mono text-muted flex justify-between items-center">
                    <span>
                      Active transfer pending acceptance for:{" "}
                      <strong className="text-ink">{t.to_username}</strong>
                    </span>
                    <div className="flex items-center gap-2">
                      <span className="text-[10px] text-amber-500 font-bold uppercase">Pending</span>
                      <button
                        onClick={() => handleCancelTransfer(t.id)}
                        className="text-[10px] text-ruby hover:underline uppercase font-mono cursor-pointer"
                      >
                        Cancel Offer
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

      </div>
    </div>
  );
}
