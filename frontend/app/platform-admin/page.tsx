"use client";

import { useState, useEffect, useCallback } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://192.168.1.92:8000";

type GlobalStats = {
  total_tenants: number;
  active_tenants: number;
  total_users: number;
  total_queries: number;
  total_chunks: number;
};

type TenantRecord = {
  id: number;
  name: string;
  slug: string;
  status: string;
  join_code: string;
  created_at: string;
  owner: string;
  member_count: number;
  doc_count: number;
  chunk_count: number;
};

type TenantDetail = {
  tenant: {
    id: number;
    name: string;
    slug: string;
    status: string;
    join_code: string;
    created_at: string;
  };
  members: Array<{ id: number; username: string; role: string; created_at: string }>;
  documents: { personal: string[]; global: string[] };
  recent_activity: Array<{
    id: number;
    username: string;
    action: string;
    category: string;
    description: string;
    timestamp: string;
  }>;
};

type GlobalActivity = {
  id: number;
  tenant_id: number;
  tenant_name: string;
  user_id?: number;
  username: string;
  action: string;
  category: string;
  description: string;
  details?: string;
  timestamp: string;
};

export default function PlatformAdminDashboard() {
  const [stats, setStats] = useState<GlobalStats | null>(null);
  const [tenants, setTenants] = useState<TenantRecord[]>([]);
  const [activities, setActivities] = useState<GlobalActivity[]>([]);
  const [selectedCategory, setSelectedCategory] = useState<string>("");
  const [inspectedTenant, setInspectedTenant] = useState<TenantDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState<boolean>(true);

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
    if (res.status === 403) {
      router.push("/");
      throw new Error("Access Denied: Platform SuperAdmin privileges required.");
    }
    return res;
  }, [router]);

  const loadData = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      // 1. Stats
      const statsRes = await authFetch(`${API_URL}/platform/stats`);
      if (statsRes.ok) {
        setStats(await statsRes.json());
      }

      // 2. Tenants
      const tenantsRes = await authFetch(`${API_URL}/platform/tenants`);
      if (tenantsRes.ok) {
        setTenants(await tenantsRes.json());
      }

      // 3. Activity
      const catParam = selectedCategory ? `?category=${selectedCategory}&limit=100` : "?limit=100";
      const actRes = await authFetch(`${API_URL}/platform/activity${catParam}`);
      if (actRes.ok) {
        setActivities(await actRes.json());
      }
    } catch (err: unknown) {
      if (err instanceof Error) {
        setError(err.message);
      } else {
        setError("Failed to load platform data");
      }
    } finally {
      setIsLoading(false);
    }
  }, [authFetch, selectedCategory]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  const inspectTenant = async (tenantId: number) => {
    try {
      const res = await authFetch(`${API_URL}/platform/tenants/${tenantId}`);
      if (res.ok) {
        setInspectedTenant(await res.json());
      }
    } catch (err) {
      console.error(err);
    }
  };

  const toggleTenantStatus = async (tenantId: number, currentStatus: string) => {
    const newStatus = currentStatus === "active" ? "suspended" : "active";
    if (!confirm(`Change tenant status to '${newStatus}'?`)) return;

    try {
      const res = await authFetch(`${API_URL}/platform/tenants/${tenantId}/status`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ status: newStatus }),
      });
      if (res.ok) {
        setSuccessMsg(`Tenant status updated to ${newStatus}.`);
        await loadData();
        if (inspectedTenant && inspectedTenant.tenant.id === tenantId) {
          await inspectTenant(tenantId);
        }
      }
    } catch (err) {
      console.error(err);
    }
  };

  const purgeTenant = async (tenantId: number, tenantName: string) => {
    const confirmation = prompt(
      `CRITICAL ACTION: This will permanently delete '${tenantName}', all its users, files, vector embeddings, and activity history.\nType the company name exactly to proceed:`
    );

    if (confirmation !== tenantName) {
      alert("Confirmation mismatch. Deletion cancelled.");
      return;
    }

    try {
      const res = await authFetch(`${API_URL}/platform/tenants/${tenantId}`, {
        method: "DELETE",
      });

      if (res.ok) {
        const result = await res.json();
        setSuccessMsg(`Organization '${tenantName}' successfully purged (${result.chunks_purged} vector chunks deleted).`);
        setInspectedTenant(null);
        await loadData();
      } else {
        const err = await res.json();
        alert(err.detail || "Failed to purge tenant");
      }
    } catch (err) {
      console.error(err);
    }
  };

  return (
    <div className="min-h-screen bg-paper text-ink p-4 sm:p-8">
      <div className="max-w-6xl mx-auto space-y-6">

        {/* Global Control Plane Header */}
        <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4 bg-paper-2 p-5 rounded-card border border-rule">
          <div>
            <div className="flex items-center gap-2 mb-1">
              <span className="w-2.5 h-2.5 rounded-full bg-accent animate-pulse" />
              <span className="font-mono text-xs uppercase tracking-wider text-muted font-bold">
                Platform Control Plane // System SuperAdmin
              </span>
              <span className="font-mono text-[10px] px-2 py-0.5 rounded border border-emerald-500/40 bg-emerald-500/10 text-emerald font-semibold uppercase">
                🌐 Global Auditor
              </span>
            </div>
            <h1 className="text-xl sm:text-2xl font-display font-semibold text-ink tracking-tight">
              Enterprise Multi-Tenant Monitor & Telemetry
            </h1>
          </div>
          <div className="flex items-center gap-2 flex-wrap">
            <button
              onClick={() => loadData()}
              className="px-3.5 py-1.5 bg-paper hover:bg-paper-3 rounded-base border border-rule text-xs font-mono uppercase tracking-wider text-ink transition-colors cursor-pointer"
            >
              ↻ Refresh All
            </button>
            <Link
              href="/admin"
              className="px-3.5 py-1.5 bg-paper hover:bg-paper-3 rounded-base border border-rule text-xs font-mono uppercase tracking-wider text-ink transition-colors"
            >
              Tenant Admin →
            </Link>
            <Link
              href="/"
              className="px-3.5 py-1.5 bg-accent hover:bg-accent-hover text-accent-ink rounded-base text-xs font-mono uppercase tracking-wider font-semibold transition-colors"
            >
              ← Chat Workspace
            </Link>
          </div>
        </div>

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

        {/* Global Platform Metrics */}
        <div className="grid grid-cols-2 sm:grid-cols-5 gap-3">
          <div className="bg-paper-2 p-4 rounded-card border border-rule">
            <span className="font-mono text-[11px] uppercase tracking-wider text-muted block mb-1">
              Total Tenants
            </span>
            <p className="text-2xl font-display font-bold text-ink">
              {stats?.total_tenants || 0}
            </p>
          </div>
          <div className="bg-paper-2 p-4 rounded-card border border-rule">
            <span className="font-mono text-[11px] uppercase tracking-wider text-muted block mb-1">
              Active Tenants
            </span>
            <p className="text-2xl font-display font-bold text-emerald">
              {stats?.active_tenants || 0}
            </p>
          </div>
          <div className="bg-paper-2 p-4 rounded-card border border-rule">
            <span className="font-mono text-[11px] uppercase tracking-wider text-muted block mb-1">
              Platform Users
            </span>
            <p className="text-2xl font-display font-bold text-ink">
              {stats?.total_users || 0}
            </p>
          </div>
          <div className="bg-paper-2 p-4 rounded-card border border-rule">
            <span className="font-mono text-[11px] uppercase tracking-wider text-muted block mb-1">
              Total Chunks
            </span>
            <p className="text-2xl font-display font-bold text-ink">
              {stats?.total_chunks || 0}
            </p>
          </div>
          <div className="bg-paper-2 p-4 rounded-card border border-rule col-span-2 sm:col-span-1">
            <span className="font-mono text-[11px] uppercase tracking-wider text-muted block mb-1">
              Executed Queries
            </span>
            <p className="text-2xl font-display font-bold text-accent">
              {stats?.total_queries || 0}
            </p>
          </div>
        </div>

        {/* REGISTERED TENANTS DIRECTORY */}
        <div className="bg-paper-2 p-5 sm:p-6 rounded-card border border-rule space-y-4">
          <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-2 pb-3 border-b border-rule">
            <div>
              <h2 className="text-base font-display font-semibold text-ink">
                Registered Tenant Organizations
              </h2>
              <p className="text-xs text-muted mt-0.5">
                Multi-tenant organizations provisioned on this platform with dedicated isolation boundaries.
              </p>
            </div>
            <span className="font-mono text-xs text-muted">
              {tenants.length} Organizations Active
            </span>
          </div>

          <div className="overflow-x-auto border border-rule rounded-base bg-paper">
            <table className="w-full text-left border-collapse">
              <thead>
                <tr className="border-b border-rule bg-paper-3 text-[11px] font-mono uppercase tracking-wider text-ink">
                  <th className="p-3">Organization</th>
                  <th className="p-3">Owner (SuperAdmin)</th>
                  <th className="p-3">Members</th>
                  <th className="p-3">Docs / Chunks</th>
                  <th className="p-3">Status</th>
                  <th className="p-3 text-right">Actions</th>
                </tr>
              </thead>
              <tbody className="text-xs divide-y divide-rule font-body">
                {tenants.map((t) => (
                  <tr key={t.id} className="hover:bg-paper-2 transition-colors">
                    <td className="p-3">
                      <div className="font-semibold text-ink">{t.name}</div>
                      <div className="font-mono text-[11px] text-muted">/{t.slug} · ID #{t.id}</div>
                    </td>
                    <td className="p-3 font-mono text-ink">
                      {t.owner}
                    </td>
                    <td className="p-3 font-mono text-ink">
                      {t.member_count}
                    </td>
                    <td className="p-3 font-mono text-muted">
                      {t.doc_count} docs ({t.chunk_count} chks)
                    </td>
                    <td className="p-3 font-mono">
                      <span className={`px-2 py-0.5 rounded text-[10px] font-bold uppercase ${
                        t.status === "active"
                          ? "bg-emerald-500/10 text-emerald border border-emerald-500/30"
                          : "bg-ruby-subtle text-ruby border border-ruby/30"
                      }`}>
                        {t.status}
                      </span>
                    </td>
                    <td className="p-3 text-right">
                      <div className="flex items-center justify-end gap-1.5">
                        <button
                          onClick={() => inspectTenant(t.id)}
                          className="px-2.5 py-1 bg-paper-2 hover:bg-paper-3 border border-rule rounded-base font-mono text-xs text-ink cursor-pointer"
                        >
                          Inspect
                        </button>
                        <button
                          onClick={() => toggleTenantStatus(t.id, t.status)}
                          className="px-2.5 py-1 bg-paper-2 hover:bg-paper-3 border border-rule rounded-base font-mono text-xs text-muted hover:text-ink cursor-pointer"
                        >
                          {t.status === "active" ? "Suspend" : "Activate"}
                        </button>
                        {t.id !== 1 && (
                          <button
                            onClick={() => purgeTenant(t.id, t.name)}
                            className="px-2.5 py-1 bg-ruby-subtle hover:bg-ruby/20 border border-ruby/30 rounded-base font-mono text-xs text-ruby cursor-pointer"
                          >
                            Purge
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        {/* INSPECTED TENANT MODAL / PANEL */}
        {inspectedTenant && (
          <div className="bg-paper-2 p-5 sm:p-6 rounded-card border-2 border-accent space-y-4">
            <div className="flex justify-between items-center pb-3 border-b border-rule">
              <div>
                <span className="font-mono text-xs uppercase tracking-wider text-accent font-bold">
                  Organization Audit Inspection
                </span>
                <h3 className="text-lg font-display font-bold text-ink">
                  {inspectedTenant.tenant.name} (#{inspectedTenant.tenant.id})
                </h3>
              </div>
              <button
                onClick={() => setInspectedTenant(null)}
                className="px-3 py-1 bg-paper border border-rule rounded-base text-xs font-mono text-muted hover:text-ink cursor-pointer"
              >
                ✕ Close Inspector
              </button>
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
              {/* Member list */}
              <div className="bg-paper p-3 rounded-base border border-rule">
                <span className="font-mono text-[11px] uppercase font-bold text-muted block mb-2">
                  Members ({inspectedTenant.members.length})
                </span>
                <ul className="text-xs space-y-1 font-mono">
                  {inspectedTenant.members.map((m) => (
                    <li key={m.id} className="flex justify-between">
                      <span className="text-ink">{m.username}</span>
                      <span className="text-muted uppercase text-[10px]">{m.role}</span>
                    </li>
                  ))}
                </ul>
              </div>

              {/* Document list */}
              <div className="bg-paper p-3 rounded-base border border-rule">
                <span className="font-mono text-[11px] uppercase font-bold text-muted block mb-2">
                  Company Corpus Docs ({inspectedTenant.documents.global.length})
                </span>
                <ul className="text-xs space-y-1 font-mono truncate">
                  {inspectedTenant.documents.global.length === 0 ? (
                    <li className="text-muted">No company docs</li>
                  ) : (
                    inspectedTenant.documents.global.map((d, i) => (
                      <li key={i} className="text-ink truncate" title={d}>
                        • {d}
                      </li>
                    ))
                  )}
                </ul>
              </div>

              {/* Join code info */}
              <div className="bg-paper p-3 rounded-base border border-rule">
                <span className="font-mono text-[11px] uppercase font-bold text-muted block mb-2">
                  Security & Metadata
                </span>
                <div className="text-xs font-mono space-y-1">
                  <div>Join Code: <strong className="text-accent">{inspectedTenant.tenant.join_code}</strong></div>
                  <div>Status: <span className="uppercase">{inspectedTenant.tenant.status}</span></div>
                  <div>Created: {new Date(inspectedTenant.tenant.created_at).toLocaleDateString()}</div>
                </div>
              </div>
            </div>
          </div>
        )}

        {/* REAL-TIME CROSS-TENANT ACTIVITY FEED */}
        <div className="bg-paper-2 p-5 sm:p-6 rounded-card border border-rule space-y-4">
          <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-3 pb-3 border-b border-rule">
            <div>
              <h2 className="text-base font-display font-semibold text-ink">
                Global Cross-Tenant Activity Stream
              </h2>
              <p className="text-xs text-muted mt-0.5">
                Real-time audit log of all events across organizations.
              </p>
            </div>
            <div className="flex items-center gap-2">
              <span className="text-xs font-mono text-muted uppercase">Category:</span>
              <select
                value={selectedCategory}
                onChange={(e) => setSelectedCategory(e.target.value)}
                className="bg-paper border border-rule text-ink text-xs font-mono rounded-base px-2 py-1 focus:outline-none focus:border-accent"
              >
                <option value="">ALL CATEGORIES</option>
                <option value="QUERY">QUERY</option>
                <option value="KNOWLEDGE">KNOWLEDGE</option>
                <option value="GOVERNANCE">GOVERNANCE</option>
                <option value="AUTH">AUTH</option>
              </select>
            </div>
          </div>

          {activities.length === 0 ? (
            <div className="text-center py-8 border border-dashed border-rule rounded-base bg-paper text-muted text-xs font-mono">
              [NO_CROSS_TENANT_ACTIVITY_RECORDED]
            </div>
          ) : (
            <div className="overflow-x-auto border border-rule rounded-base bg-paper">
              <table className="w-full text-left border-collapse">
                <thead>
                  <tr className="border-b border-rule bg-paper-3 text-[11px] font-mono uppercase tracking-wider text-ink">
                    <th className="p-2.5">Time</th>
                    <th className="p-2.5">Organization</th>
                    <th className="p-2.5">User</th>
                    <th className="p-2.5">Category</th>
                    <th className="p-2.5">Action & Description</th>
                  </tr>
                </thead>
                <tbody className="text-xs divide-y divide-rule font-mono">
                  {activities.map((act) => (
                    <tr key={act.id} className="hover:bg-paper-2 transition-colors">
                      <td className="p-2.5 text-muted whitespace-nowrap">
                        {new Date(act.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })}
                      </td>
                      <td className="p-2.5 font-bold text-ink whitespace-nowrap">
                        {act.tenant_name}
                      </td>
                      <td className="p-2.5 text-muted whitespace-nowrap">
                        {act.username}
                      </td>
                      <td className="p-2.5">
                        <span className={`px-1.5 py-0.5 rounded text-[10px] uppercase font-bold ${
                          act.category === "QUERY" ? "bg-blue-500/10 text-blue-400 border border-blue-500/30" :
                          act.category === "KNOWLEDGE" ? "bg-emerald-500/10 text-emerald-400 border border-emerald-500/30" :
                          act.category === "GOVERNANCE" ? "bg-amber-500/10 text-amber-400 border border-amber-500/30" :
                          "bg-purple-500/10 text-purple-400 border border-purple-500/30"
                        }`}>
                          {act.category}
                        </span>
                      </td>
                      <td className="p-2.5 text-ink font-body">
                        {act.description}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>

      </div>
    </div>
  );
}
