"use client";

import { useState, useRef, useEffect, useCallback } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { getApiUrl } from "@/lib/api";
import CyberSpinner from "@/components/CyberSpinner";
import TerminalSkeleton from "@/components/TerminalSkeleton";
import TaskProgressStepper from "@/components/TaskProgressStepper";
import { useTaskPolling } from "@/hooks/useTaskPolling";

type Stats = {
  tenant_id: number;
  tenant_name: string;
  allowed_domains?: string;
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
  const API_URL = getApiUrl();
  const [activeTab, setActiveTab] = useState<"roster" | "corpus" | "graph" | "activity" | "settings" | "sso">("roster");
  const [stats, setStats] = useState<Stats | null>(null);
  const [requests, setRequests] = useState<RoleRequest[]>([]);
  const [users, setUsers] = useState<UserData[]>([]);
  const [activities, setActivities] = useState<ActivityItem[]>([]);
  const [activityCategory, setActivityCategory] = useState<string>("");
  const [activitySearch, setActivitySearch] = useState<string>("");
  const [activityUserId, setActivityUserId] = useState<string>("");
  const [activityTimeRange, setActivityTimeRange] = useState<"all" | "today" | "7d" | "30d">("all");
  const [activityOffset, setActivityOffset] = useState<number>(0);
  const [activityTotal, setActivityTotal] = useState<number>(0);
  const [isExporting, setIsExporting] = useState<boolean>(false);
  const [isLoadingActivity, setIsLoadingActivity] = useState<boolean>(false);
  const [isLoadingStats, setIsLoadingStats] = useState<boolean>(true);
  const [selectedLogDetails, setSelectedLogDetails] = useState<ActivityItem | null>(null);
  const [joinCode, setJoinCode] = useState<string>("");
  const [isKeyCopied, setIsKeyCopied] = useState<boolean>(false);
  const [pendingTransfers, setPendingTransfers] = useState<PendingTransfer[]>([]);
  const [transferTargetUserId, setTransferTargetUserId] = useState<number | "">("");

  // Enterprise Single Sign-On (SSO) & SAML/OIDC (Phase 12)
  const [ssoConfig, setSsoConfig] = useState<{
    configured: boolean;
    id?: number;
    tenant_id?: number;
    idp_type: string;
    is_enabled: boolean;
    enforce_sso: boolean;
    idp_entity_id: string;
    idp_sso_url: string;
    idp_x509_cert: string;
    idp_metadata_xml: string;
    oidc_issuer_url: string;
    oidc_client_id: string;
    oidc_client_secret: string;
    oidc_scopes: string;
    allowed_domains: string;
    default_role: string;
    role_mapping_json: string;
    sp_metadata_url?: string;
    sp_acs_url?: string;
    sp_entity_id?: string;
  }>({
    configured: false,
    idp_type: "saml",
    is_enabled: true,
    enforce_sso: false,
    idp_entity_id: "",
    idp_sso_url: "",
    idp_x509_cert: "",
    idp_metadata_xml: "",
    oidc_issuer_url: "",
    oidc_client_id: "",
    oidc_client_secret: "",
    oidc_scopes: "openid email profile groups",
    allowed_domains: "",
    default_role: "user",
    role_mapping_json: '{\n  "Admins": "admin",\n  "Editors": "editor"\n}',
  });
  const [isLoadingSso, setIsLoadingSso] = useState<boolean>(false);
  const [isSavingSso, setIsSavingSso] = useState<boolean>(false);
  const [isRevokingSessions, setIsRevokingSessions] = useState<boolean>(false);
  const [ssoFeedback, setSsoFeedback] = useState<{ type: "success" | "error"; msg: string } | null>(null);
  const [ssoCopiedItem, setSsoCopiedItem] = useState<string | null>(null);

  // Knowledge Graph State (Phase 7)
  const [graphStats, setGraphStats] = useState<{
    node_count: number;
    edge_count: number;
    entity_types: Record<string, number>;
    relation_types: Record<string, number>;
    top_entities: any[];
  } | null>(null);
  const [graphSearchQuery, setGraphSearchQuery] = useState<string>("");
  const [graphDepth, setGraphDepth] = useState<number>(2);
  const [graphData, setGraphData] = useState<{ nodes: any[]; edges: any[] }>({ nodes: [], edges: [] });
  const [isLoadingGraph, setIsLoadingGraph] = useState<boolean>(false);
  const [isRebuildingGraph, setIsRebuildingGraph] = useState<boolean>(false);
  const [selectedEntityId, setSelectedEntityId] = useState<string | null>(null);

  // Enterprise Corporate Domain & SSO Routing (Pillar 8)
  const [allowedDomains, setAllowedDomains] = useState<string>("");
  const [domainInput, setDomainInput] = useState<string>("");
  const [isSavingDomains, setIsSavingDomains] = useState<boolean>(false);
  const [domainFeedback, setDomainFeedback] = useState<{ type: "success" | "error"; msg: string } | null>(null);
  const [oauthProviders, setOauthProviders] = useState<{ google?: boolean; github?: boolean; microsoft?: boolean }>({});

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

  const taskPolling = useTaskPolling(authFetch);

  const fetchStatsAndData = useCallback(async () => {
    setIsLoadingStats(true);
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
        if (!me.role || !["admin", "superadmin"].includes(me.role)) {
          router.push("/");
          return;
        }
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

      // Fetch OAuth Providers
      try {
        const provRes = await authFetch(`${API_URL}/auth/oauth/providers`);
        if (provRes.ok) {
          const provData = await provRes.json();
          setOauthProviders(provData);
        }
      } catch (e) {
        console.warn("Could not load OAuth provider status", e);
      }

      // Fetch Allowed Corporate Domains
      try {
        const domRes = await authFetch(`${API_URL}/auth/tenant/domains`);
        if (domRes.ok) {
          const domData = await domRes.json();
          const domains = domData.allowed_domains || "";
          setAllowedDomains(domains);
          setDomainInput(domains);
        }
      } catch (e) {
        console.warn("Could not load tenant domains", e);
      }
    } catch (err: unknown) {
      if (err instanceof Error) {
        setError(err.message);
      } else {
        setError("Failed to load administration data");
      }
    } finally {
      setIsLoadingStats(false);
    }
  }, [API_URL, authFetch]);

  const fetchActivity = useCallback(async (
    categoryFilter = activityCategory,
    userFilter = activityUserId,
    searchFilter = activitySearch,
    timeRange = activityTimeRange,
    offset = activityOffset
  ) => {
    setIsLoadingActivity(true);
    try {
      const params = new URLSearchParams();
      if (categoryFilter && categoryFilter !== "ALL") params.append("category", categoryFilter);
      if (userFilter) params.append("user_id", userFilter);
      if (searchFilter.trim()) params.append("search", searchFilter.trim());

      const now = new Date();
      if (timeRange === "today") {
        const startOfDay = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate(), 0, 0, 0));
        params.append("start_date", startOfDay.toISOString());
      } else if (timeRange === "7d") {
        const sevenDaysAgo = new Date(now.getTime() - 7 * 24 * 60 * 60 * 1000);
        params.append("start_date", sevenDaysAgo.toISOString());
      } else if (timeRange === "30d") {
        const thirtyDaysAgo = new Date(now.getTime() - 30 * 24 * 60 * 60 * 1000);
        params.append("start_date", thirtyDaysAgo.toISOString());
      }

      params.append("limit", "50");
      params.append("offset", String(offset));

      const res = await authFetch(`${API_URL}/admin/activity?${params.toString()}`);
      if (res.ok) {
        const data = await res.json();
        if (Array.isArray(data)) {
          setActivities(data);
          setActivityTotal(data.length);
        } else {
          setActivities(data.logs || []);
          setActivityTotal(data.total || 0);
        }
      }
    } catch (err) {
      console.error("Activity load error:", err);
    } finally {
      setIsLoadingActivity(false);
    }
  }, [API_URL, authFetch, activityCategory, activityUserId, activitySearch, activityTimeRange, activityOffset]);

  const handleExportActivity = async (format: "csv" | "json") => {
    setIsExporting(true);
    try {
      const params = new URLSearchParams();
      params.append("format", format);
      if (activityCategory && activityCategory !== "ALL") params.append("category", activityCategory);
      if (activityUserId) params.append("user_id", activityUserId);
      if (activitySearch.trim()) params.append("search", activitySearch.trim());

      const now = new Date();
      if (activityTimeRange === "today") {
        const startOfDay = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate(), 0, 0, 0));
        params.append("start_date", startOfDay.toISOString());
      } else if (activityTimeRange === "7d") {
        const sevenDaysAgo = new Date(now.getTime() - 7 * 24 * 60 * 60 * 1000);
        params.append("start_date", sevenDaysAgo.toISOString());
      } else if (activityTimeRange === "30d") {
        const thirtyDaysAgo = new Date(now.getTime() - 30 * 24 * 60 * 60 * 1000);
        params.append("start_date", thirtyDaysAgo.toISOString());
      }

      const res = await authFetch(`${API_URL}/admin/activity/export?${params.toString()}`);
      if (!res.ok) {
        alert("Failed to export audit log");
        return;
      }

      const blob = await res.blob();
      const contentDisposition = res.headers.get("content-disposition");
      let filename = `audit_log_${format}_${Date.now()}.${format}`;
      if (contentDisposition) {
        const match = contentDisposition.match(/filename="?([^"]+)"?/);
        if (match && match[1]) filename = match[1];
      }

      const downloadUrl = window.URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = downloadUrl;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      a.remove();
      window.URL.revokeObjectURL(downloadUrl);
      setSuccessMsg(`Audit log exported as ${filename}`);
    } catch (err) {
      console.error("Export error:", err);
      alert("Error exporting audit log.");
    } finally {
      setIsExporting(false);
    }
  };

  const fetchGraphData = useCallback(async (query = "", depth?: number) => {
    setIsLoadingGraph(true);
    const effectiveDepth = depth !== undefined ? depth : graphDepth;
    try {
      const statsRes = await authFetch(`${API_URL}/graph/stats`);
      if (statsRes && statsRes.ok) {
        const sData = await statsRes.json();
        setGraphStats(sData);
      }

      const qParam = query.trim() ? `?query=${encodeURIComponent(query.trim())}&depth=${effectiveDepth}` : `?depth=${effectiveDepth}`;
      const subRes = await authFetch(`${API_URL}/graph/subgraph${qParam}`);
      if (subRes && subRes.ok) {
        const gData = await subRes.json();
        setGraphData({ nodes: gData.nodes || [], edges: gData.edges || [] });
      }
    } catch (err) {
      console.error("Error loading graph data:", err);
    } finally {
      setIsLoadingGraph(false);
    }
  }, [API_URL, authFetch, graphDepth]);

  const handleRebuildGraph = async () => {
    if (!confirm("Rebuild Knowledge Graph from all existing corpus documents? This will re-extract entities and relationships.")) return;
    setIsRebuildingGraph(true);
    setError(null);
    try {
      const res = await authFetch(`${API_URL}/graph/rebuild`, { method: "POST" });
      if (res && res.ok) {
        const data = await res.json();
        setSuccessMsg(data.message || "Knowledge Graph rebuilt successfully");
        await fetchGraphData(graphSearchQuery);
      } else {
        const err = await res?.json();
        setError(err?.detail || "Failed to rebuild graph");
      }
    } catch (err: any) {
      setError(err?.message || "Failed to rebuild graph");
    } finally {
      setIsRebuildingGraph(false);
    }
  };

  const fetchSSOConfig = useCallback(async () => {
    setIsLoadingSso(true);
    setSsoFeedback(null);
    try {
      const res = await authFetch(`${API_URL}/admin/sso/config`);
      if (res.ok) {
        const data = await res.json();
        setSsoConfig({
          configured: data.configured ?? !!data.id,
          id: data.id,
          tenant_id: data.tenant_id,
          idp_type: data.idp_type || "saml",
          is_enabled: data.is_enabled ?? true,
          enforce_sso: data.enforce_sso ?? false,
          idp_entity_id: data.idp_entity_id || "",
          idp_sso_url: data.idp_sso_url || "",
          idp_x509_cert: data.idp_x509_cert || "",
          idp_metadata_xml: data.idp_metadata_xml || "",
          oidc_issuer_url: data.oidc_issuer_url || "",
          oidc_client_id: data.oidc_client_id || "",
          oidc_client_secret: data.oidc_client_secret || "",
          oidc_scopes: data.oidc_scopes || "openid email profile groups",
          allowed_domains: data.allowed_domains || "",
          default_role: data.default_role || "user",
          role_mapping_json: data.role_mapping_json || '{\n  "Admins": "admin",\n  "Editors": "editor"\n}',
          sp_metadata_url: data.sp_metadata_url,
          sp_acs_url: data.sp_acs_url,
          sp_entity_id: data.sp_entity_id,
        });
      }
    } catch (err: any) {
      console.error("Failed to load SSO configuration:", err);
    } finally {
      setIsLoadingSso(false);
    }
  }, [API_URL, authFetch]);

  useEffect(() => {
    const role = localStorage.getItem("role");
    if (!role || !["admin", "superadmin"].includes(role)) {
      router.push("/login");
      return;
    }
    fetchStatsAndData();
  }, [fetchStatsAndData, router]);

  useEffect(() => {
    if (activeTab === "activity") {
      fetchActivity(activityCategory, activityUserId, activitySearch, activityTimeRange, activityOffset);
    } else if (activeTab === "graph") {
      fetchGraphData();
    } else if (activeTab === "sso") {
      fetchSSOConfig();
    }
  }, [activeTab, activityCategory, activityUserId, activitySearch, activityTimeRange, activityOffset, fetchActivity, fetchGraphData, fetchSSOConfig]);

  const handleUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    setIsUploading(true);
    setError(null);
    const formData = new FormData();
    formData.append("file", file);

    try {
      const res = await authFetch(`${API_URL}/admin/upload_global`, {
        method: "POST",
        body: formData,
      });

      if (res.ok) {
        const data = await res.json();
        if (data.task_id) {
          taskPolling.startPolling(data.task_id, file.name, {
            onSuccess: async () => {
              setSuccessMsg(`Document '${file.name}' successfully ingested into company corpus.`);
              await fetchStatsAndData();
            },
            onError: (errMsg) => {
              setError(`Ingestion failed for '${file.name}': ${errMsg}`);
            },
          });
        } else {
          setSuccessMsg(`Document '${file.name}' successfully ingested into company corpus.`);
          await fetchStatsAndData();
        }
      } else {
        const err = await res.json();
        setError(`Upload failed: ${err.detail || "Server error"}`);
      }
    } catch (error) {
      console.error("Upload error:", error);
      setError("Failed to connect to backend for upload.");
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

  const handleSaveDomains = async (e?: React.FormEvent) => {
    if (e) e.preventDefault();
    setDomainFeedback(null);

    const rawList = domainInput
      .split(",")
      .map((d) => d.trim().toLowerCase())
      .filter(Boolean);

    const publicDomains = [
      "gmail.com",
      "yahoo.com",
      "outlook.com",
      "hotmail.com",
      "icloud.com",
      "mail.com",
      "proton.me",
      "protonmail.com",
      "aol.com",
    ];

    for (const d of rawList) {
      if (publicDomains.includes(d)) {
        setDomainFeedback({
          type: "error",
          msg: `Public domain '${d}' cannot be configured for corporate SSO auto-routing. Please provide verified corporate hostnames.`,
        });
        return;
      }
      if (!/^[a-z0-9.-]+\.[a-z]{2,}$/i.test(d)) {
        setDomainFeedback({
          type: "error",
          msg: `Invalid domain format: '${d}'. Expected standard format like 'acme.com'.`,
        });
        return;
      }
    }

    setIsSavingDomains(true);
    try {
      const sanitized = rawList.join(", ");
      const res = await authFetch(`${API_URL}/auth/tenant/domains`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ allowed_domains: sanitized }),
      });

      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.detail || "Failed to update tenant corporate domains");
      }

      const data = await res.json();
      setAllowedDomains(data.allowed_domains || "");
      setDomainInput(data.allowed_domains || "");
      setDomainFeedback({
        type: "success",
        msg: "Corporate domains successfully updated and active for OAuth SSO auto-routing.",
      });
      setTimeout(() => setDomainFeedback(null), 5000);
      await fetchStatsAndData();
    } catch (err: unknown) {
      setDomainFeedback({
        type: "error",
        msg: err instanceof Error ? err.message : "Error saving corporate domains",
      });
    } finally {
      setIsSavingDomains(false);
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

  const copyToClipboard = (text: string, label: string) => {
    navigator.clipboard.writeText(text);
    setSsoCopiedItem(label);
    setTimeout(() => setSsoCopiedItem(null), 2000);
  };

  const handleSaveSSOConfig = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsSavingSso(true);
    setSsoFeedback(null);
    try {
      const res = await authFetch(`${API_URL}/admin/sso/config`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(ssoConfig),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || "Failed to save SSO configuration");
      }
      const saved = await res.json();
      setSsoConfig((prev) => ({
        ...prev,
        ...saved,
        configured: true,
      }));
      setSsoFeedback({ type: "success", msg: "SSO configuration saved successfully and active!" });
    } catch (err: any) {
      setSsoFeedback({ type: "error", msg: err.message || "Failed to save SSO configuration" });
    } finally {
      setIsSavingSso(false);
    }
  };

  const handleDeleteSSOConfig = async () => {
    if (!window.confirm("Disable Single Sign-On and delete this configuration? Corporate users will revert to standard credentials.")) {
      return;
    }
    setIsSavingSso(true);
    setSsoFeedback(null);
    try {
      const res = await authFetch(`${API_URL}/admin/sso/config`, { method: "DELETE" });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || "Failed to delete SSO configuration");
      }
      setSsoConfig({
        configured: false,
        idp_type: "saml",
        is_enabled: false,
        enforce_sso: false,
        idp_entity_id: "",
        idp_sso_url: "",
        idp_x509_cert: "",
        idp_metadata_xml: "",
        oidc_issuer_url: "",
        oidc_client_id: "",
        oidc_client_secret: "",
        oidc_scopes: "openid email profile groups",
        allowed_domains: "",
        default_role: "user",
        role_mapping_json: '{\n  "Admins": "admin",\n  "Editors": "editor"\n}',
      });
      setSsoFeedback({ type: "success", msg: "Single Sign-On configuration removed." });
    } catch (err: any) {
      setSsoFeedback({ type: "error", msg: err.message || "Failed to delete SSO configuration" });
    } finally {
      setIsSavingSso(false);
    }
  };

  const handleRevokeAllSessions = async () => {
    if (!window.confirm("EMERGENCY REVOCATION:\n\nRevoke all active sessions for your organization? This will instantly invalidate all active JWT tokens in Redis. Everyone (including you) will be logged out.")) {
      return;
    }
    setIsRevokingSessions(true);
    setSsoFeedback(null);
    try {
      const res = await authFetch(`${API_URL}/auth/sso/revoke`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          tenant_id: ssoConfig.tenant_id ?? stats?.tenant_id ?? (localStorage.getItem("tenant_id") ? Number(localStorage.getItem("tenant_id")) : undefined),
          all_tenants: false,
        }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || "Session revocation failed");
      }
      alert("All organization sessions have been revoked. Please sign in again.");
      localStorage.removeItem("token");
      router.push("/login");
    } catch (err: any) {
      setSsoFeedback({ type: "error", msg: err.message || "Failed to revoke active sessions" });
      setIsRevokingSessions(false);
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
        {isLoadingStats && !stats ? (
          <TerminalSkeleton variant="stats" />
        ) : (
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
        )}

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
            onClick={() => setActiveTab("graph")}
            className={`py-2 px-4 text-xs font-mono uppercase tracking-wider border-b-2 font-semibold transition-colors cursor-pointer ${
              activeTab === "graph"
                ? "border-accent text-ink"
                : "border-transparent text-muted hover:text-ink"
            }`}
          >
            Knowledge Graph ({graphStats?.node_count || 0})
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
          <button
            onClick={() => setActiveTab("sso")}
            className={`py-2 px-4 text-xs font-mono uppercase tracking-wider border-b-2 font-semibold transition-colors cursor-pointer flex items-center gap-1.5 ${
              activeTab === "sso"
                ? "border-accent text-ink"
                : "border-transparent text-muted hover:text-ink"
            }`}
          >
            <span>SSO & Directory Sync</span>
            {ssoConfig.configured && (
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-500" />
            )}
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
                  disabled={isUploading || taskPolling.isPolling}
                  className="px-3.5 py-2 bg-accent hover:bg-accent-hover text-accent-ink rounded-base text-xs font-mono uppercase tracking-wider font-semibold transition-colors disabled:opacity-50 cursor-pointer flex items-center gap-1.5"
                >
                  {taskPolling.isPolling ? (
                    <>
                      <CyberSpinner size="xs" variant="ink" />
                      <span>{taskPolling.progress?.stage || "INGESTING"} ({taskPolling.progress?.pct || 10}%)</span>
                    </>
                  ) : isUploading ? (
                    "Uploading..."
                  ) : (
                    "+ Ingest Company Document"
                  )}
                </button>
              </div>
            </div>

            {/* Active Ingestion Task Stepper */}
            {(taskPolling.isPolling || taskPolling.isComplete || taskPolling.error) && (
              <TaskProgressStepper
                progress={taskPolling.progress}
                filename={taskPolling.filename}
                error={taskPolling.error}
                isComplete={taskPolling.isComplete}
                onDismiss={taskPolling.reset}
                className="mb-4"
              />
            )}

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

        {/* TAB: KNOWLEDGE GRAPH EXPLORER (PHASE 7) */}
        {activeTab === "graph" && (
          <div className="space-y-6">
            {/* GRAPH OVERVIEW BANNER */}
            <div className="bg-paper-2 p-5 sm:p-6 rounded-card border border-rule">
              <div className="flex flex-col md:flex-row justify-between items-start md:items-center gap-4 pb-4 border-b border-rule">
                <div>
                  <div className="flex items-center gap-2">
                    <h2 className="text-base font-display font-semibold text-ink">
                      Enterprise Knowledge Graph & Relational Entity Network
                    </h2>
                    <span className="px-2 py-0.5 rounded text-[10px] font-mono font-bold bg-purple-500/10 text-purple-400 border border-purple-500/30">
                      HYBRID GRAPH RAG
                    </span>
                  </div>
                  <p className="text-xs text-muted mt-1">
                    Multi-hop relational network extracted from company corpus. Enables cross-document reasoning across policies, incidents, departments, and systems.
                  </p>
                </div>
                <div className="flex items-center gap-2">
                  <button
                    onClick={handleRebuildGraph}
                    disabled={isRebuildingGraph}
                    className="flex items-center gap-2 px-3 py-1.5 bg-paper hover:bg-accent-subtle border border-rule hover:border-accent text-xs font-mono font-semibold text-ink hover:text-accent rounded-base transition-colors cursor-pointer disabled:opacity-50"
                  >
                    {isRebuildingGraph ? <CyberSpinner className="w-3.5 h-3.5" /> : "⚡"}
                    <span>{isRebuildingGraph ? "Rebuilding Graph..." : "Rebuild Knowledge Graph"}</span>
                  </button>
                </div>
              </div>

              {/* STATS TILES */}
              <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mt-5">
                <div className="p-3.5 bg-paper rounded-base border border-rule">
                  <div className="text-[10px] font-mono uppercase text-muted">Indexed Entities</div>
                  <div className="text-xl font-bold font-mono text-ink mt-0.5">{graphStats?.node_count || 0}</div>
                  <div className="text-[10px] text-muted mt-1">Nodes in active graph</div>
                </div>
                <div className="p-3.5 bg-paper rounded-base border border-rule">
                  <div className="text-[10px] font-mono uppercase text-muted">Directed Relations</div>
                  <div className="text-xl font-bold font-mono text-purple-400 mt-0.5">{graphStats?.edge_count || 0}</div>
                  <div className="text-[10px] text-muted mt-1">Cross-entity links</div>
                </div>
                <div className="p-3.5 bg-paper rounded-base border border-rule">
                  <div className="text-[10px] font-mono uppercase text-muted">Entity Categories</div>
                  <div className="text-xl font-bold font-mono text-emerald mt-0.5">
                    {Object.keys(graphStats?.entity_types || {}).length}
                  </div>
                  <div className="text-[10px] text-muted mt-1">Policies, Incidents, Systems...</div>
                </div>
                <div className="p-3.5 bg-paper rounded-base border border-rule">
                  <div className="text-[10px] font-mono uppercase text-muted">Relation Types</div>
                  <div className="text-xl font-bold font-mono text-amber-400 mt-0.5">
                    {Object.keys(graphStats?.relation_types || {}).length}
                  </div>
                  <div className="text-[10px] text-muted mt-1">AFFECTS, GOVERNS, RESOLVED...</div>
                </div>
              </div>

              {/* ENTITY TYPE PILLS */}
              {graphStats?.entity_types && Object.keys(graphStats.entity_types).length > 0 && (
                <div className="flex flex-wrap items-center gap-1.5 mt-4 pt-3 border-t border-rule/60">
                  <span className="text-[10px] font-mono uppercase text-muted font-semibold mr-1">Types:</span>
                  {Object.entries(graphStats.entity_types).map(([type, count]) => (
                    <span
                      key={type}
                      className="px-2 py-0.5 rounded text-[10px] font-mono border bg-paper-3 text-ink border-rule"
                    >
                      {type} <strong className="text-accent">({count})</strong>
                    </span>
                  ))}
                </div>
              )}
            </div>

            {/* SEARCH & TRAVERSAL CONTROLS */}
            <div className="bg-paper-2 p-4 rounded-card border border-rule flex flex-col md:flex-row items-center justify-between gap-3">
              <div className="relative flex-1 w-full">
                <input
                  type="text"
                  value={graphSearchQuery}
                  onChange={(e) => setGraphSearchQuery(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && fetchGraphData(graphSearchQuery)}
                  placeholder="Search entity (e.g. Incident Report 104, Payment Gateway, Security Policy)..."
                  className="w-full bg-paper border border-rule rounded-base px-3 py-2 text-xs text-ink placeholder:text-muted focus:outline-none focus:border-accent font-mono"
                />
              </div>
              <div className="flex items-center gap-2 w-full md:w-auto justify-end">
                <span className="text-xs font-mono text-muted">Hops:</span>
                <select
                  value={graphDepth}
                  onChange={(e) => {
                    const newDepth = Number(e.target.value);
                    setGraphDepth(newDepth);
                    fetchGraphData(graphSearchQuery, newDepth);
                  }}
                  className="bg-paper border border-rule rounded-base px-2.5 py-1.5 text-xs text-ink font-mono focus:outline-none focus:border-accent cursor-pointer"
                >
                  <option value={1}>1 Hop (Direct)</option>
                  <option value={2}>2 Hops (Connected)</option>
                  <option value={3}>3 Hops (Deep Subgraph)</option>
                </select>
                <button
                  onClick={() => fetchGraphData(graphSearchQuery)}
                  className="px-3 py-1.5 bg-accent hover:bg-accent/90 text-paper font-mono text-xs font-semibold rounded-base transition-colors cursor-pointer"
                >
                  Filter Graph
                </button>
              </div>
            </div>

            {/* GRAPH VIEW: NODES & RELATIONSHIPS SPLIT */}
            {isLoadingGraph ? (
              <div className="bg-paper-2 p-12 rounded-card border border-rule flex flex-col items-center justify-center">
                <CyberSpinner className="w-8 h-8 mb-3" />
                <span className="text-xs font-mono text-muted">Traversing knowledge graph and computing subgraphs...</span>
              </div>
            ) : graphData.nodes.length === 0 ? (
              <div className="bg-paper-2 p-12 rounded-card border border-rule text-center">
                <span className="text-3xl">🌐</span>
                <h3 className="text-sm font-semibold text-ink mt-2">No Knowledge Graph Entities Yet</h3>
                <p className="text-xs text-muted max-w-md mx-auto mt-1">
                  Upload documents to the company corpus or click &quot;Rebuild Knowledge Graph&quot; to automatically extract entities and relationships.
                </p>
                <button
                  onClick={handleRebuildGraph}
                  disabled={isRebuildingGraph}
                  className="mt-4 px-4 py-2 bg-accent text-paper font-mono text-xs font-semibold rounded-base hover:bg-accent/90 cursor-pointer"
                >
                  Extract &amp; Rebuild Graph Now
                </button>
              </div>
            ) : (
              <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
                {/* ENTITIES LIST */}
                <div className="lg:col-span-5 bg-paper-2 p-5 rounded-card border border-rule space-y-3">
                  <div className="flex items-center justify-between border-b border-rule pb-2.5">
                    <h3 className="text-xs font-mono font-bold uppercase tracking-wider text-ink">
                      Active Subgraph Entities ({graphData.nodes.length})
                    </h3>
                    <span className="text-[10px] font-mono text-muted">Click to inspect</span>
                  </div>

                  <div className="space-y-2 max-h-[500px] overflow-y-auto pr-1">
                    {graphData.nodes.map((node) => {
                      const isSelected = selectedEntityId === node.id;
                      let badgeColor = "bg-blue-500/10 text-blue-400 border-blue-500/30";
                      if (node.type === "INCIDENT") badgeColor = "bg-red-500/10 text-red-400 border-red-500/30";
                      else if (node.type === "POLICY") badgeColor = "bg-purple-500/10 text-purple-400 border-purple-500/30";
                      else if (node.type === "SYSTEM") badgeColor = "bg-cyan-500/10 text-cyan-400 border-cyan-500/30";
                      else if (node.type === "DEPARTMENT") badgeColor = "bg-emerald-500/10 text-emerald-400 border-emerald-500/30";
                      else if (node.type === "METRIC") badgeColor = "bg-amber-500/10 text-amber-400 border-amber-500/30";

                      return (
                        <div
                          key={node.id}
                          onClick={() => setSelectedEntityId(isSelected ? null : node.id)}
                          className={`p-3 rounded-base border transition-all cursor-pointer ${
                            isSelected
                              ? "bg-accent-subtle/40 border-accent shadow-xs"
                              : "bg-paper hover:bg-paper-3 border-rule"
                          }`}
                        >
                          <div className="flex items-start justify-between gap-2">
                            <span className="text-xs font-semibold text-ink">{node.label}</span>
                            <span className={`px-1.5 py-0.5 rounded text-[9px] font-mono font-bold border uppercase shrink-0 ${badgeColor}`}>
                              {node.type}
                            </span>
                          </div>
                          {node.description && (
                            <p className="text-[11px] text-muted line-clamp-2 mt-1">
                              {node.description}
                            </p>
                          )}
                          <div className="flex items-center gap-2 mt-2 pt-2 border-t border-rule/40 text-[10px] font-mono text-muted">
                            <span>Degree: <strong className="text-ink">{node.degree}</strong></span>
                            {node.sources && node.sources.length > 0 && (
                              <span className="truncate">Source: {node.sources[0]}</span>
                            )}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </div>

                {/* RELATIONSHIP EDGES */}
                <div className="lg:col-span-7 bg-paper-2 p-5 rounded-card border border-rule space-y-3">
                  <div className="flex items-center justify-between border-b border-rule pb-2.5">
                    <h3 className="text-xs font-mono font-bold uppercase tracking-wider text-ink">
                      Directed Relationship Links ({graphData.edges.length})
                    </h3>
                    {selectedEntityId && (
                      <button
                        onClick={() => setSelectedEntityId(null)}
                        className="text-[10px] font-mono text-accent hover:underline cursor-pointer"
                      >
                        Reset Filter
                      </button>
                    )}
                  </div>

                  <div className="space-y-2 max-h-[500px] overflow-y-auto pr-1">
                    {graphData.edges
                      .filter((e) => !selectedEntityId || e.source === selectedEntityId || e.target === selectedEntityId)
                      .map((edge, idx) => (
                        <div
                          key={idx}
                          className="p-3 bg-paper rounded-base border border-rule hover:border-purple-500/40 transition-colors"
                        >
                          <div className="flex flex-wrap items-center gap-2 font-mono text-xs">
                            <span className="font-semibold text-ink bg-paper-3 px-2 py-0.5 rounded border border-rule">
                              {edge.source}
                            </span>
                            <span className="text-[11px] font-bold text-purple-400 bg-purple-500/10 px-2 py-0.5 rounded border border-purple-500/20">
                              ── {edge.relation} ──▶
                            </span>
                            <span className="font-semibold text-ink bg-paper-3 px-2 py-0.5 rounded border border-rule">
                              {edge.target}
                            </span>
                          </div>
                          {edge.context && (
                            <p className="text-[11px] text-muted mt-2 italic border-l-2 border-purple-500/30 pl-2">
                              &ldquo;{edge.context}&rdquo;
                            </p>
                          )}
                          {edge.source_document && (
                            <div className="text-[10px] font-mono text-muted mt-2">
                              Extracted from: <span className="text-ink">{edge.source_document}</span>
                            </div>
                          )}
                        </div>
                      ))}
                  </div>
                </div>
              </div>
            )}
          </div>
        )}

        {/* TAB 3: ACTIVITY & AUDIT LOG */}
        {activeTab === "activity" && (
          <div className="bg-paper-2 p-5 sm:p-6 rounded-card border border-rule space-y-4">
            {/* AUDIT CONSOLE HEADER */}
            <div className="flex flex-col md:flex-row justify-between items-start md:items-center gap-4 pb-4 border-b border-rule">
              <div>
                <div className="flex items-center gap-2">
                  <h2 className="text-base font-display font-semibold text-ink">
                    Enterprise Compliance & Audit Stream
                  </h2>
                  <span className="px-2 py-0.5 rounded text-[10px] font-mono font-bold bg-emerald-500/10 text-emerald-400 border border-emerald-500/30">
                    SOC 2 READY
                  </span>
                </div>
                <p className="text-xs text-muted mt-0.5">
                  Tamper-evident logs of query executions, corpus changes, access delegations, and auth events.
                </p>
              </div>

              {/* EXPORT TOOLBAR */}
              <div className="flex items-center gap-2">
                <button
                  onClick={() => handleExportActivity("csv")}
                  disabled={isExporting}
                  className="px-3 py-1.5 bg-paper hover:bg-paper-3 border border-rule hover:border-accent text-xs font-mono uppercase tracking-wider text-ink rounded-base flex items-center gap-1.5 transition-colors disabled:opacity-50 cursor-pointer"
                  title="Export filtered audit logs as CSV for spreadsheet analysis"
                >
                  {isExporting ? <CyberSpinner size="xs" variant="accent" /> : <span>📥</span>}
                  <span>Export CSV</span>
                </button>
                <button
                  onClick={() => handleExportActivity("json")}
                  disabled={isExporting}
                  className="px-3 py-1.5 bg-paper hover:bg-paper-3 border border-rule hover:border-accent text-xs font-mono uppercase tracking-wider text-ink rounded-base flex items-center gap-1.5 transition-colors disabled:opacity-50 cursor-pointer"
                  title="Export filtered audit logs as JSON for SIEM/Datadog integration"
                >
                  {isExporting ? <CyberSpinner size="xs" variant="accent" /> : <span>📥</span>}
                  <span>Export JSON</span>
                </button>
                <button
                  onClick={() => fetchActivity()}
                  disabled={isLoadingActivity}
                  className="px-2.5 py-1.5 bg-paper hover:bg-paper-3 border border-rule text-xs font-mono text-ink rounded-base cursor-pointer disabled:opacity-50"
                  title="Refresh activity logs"
                >
                  {isLoadingActivity ? <CyberSpinner size="xs" variant="ink" /> : "↻"}
                </button>
              </div>
            </div>

            {/* FILTER TOOLBAR */}
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3 p-3 bg-paper rounded-base border border-rule">
              {/* Category Filter */}
              <div>
                <label className="text-[10px] font-mono text-muted uppercase block mb-1">Event Category</label>
                <select
                  value={activityCategory}
                  onChange={(e) => {
                    setActivityCategory(e.target.value);
                    setActivityOffset(0);
                  }}
                  className="w-full bg-paper-2 border border-rule text-ink text-xs font-mono rounded-base px-2.5 py-1.5 focus:outline-none focus:border-accent"
                >
                  <option value="">ALL CATEGORIES</option>
                  <option value="QUERY">QUERY (Inference Telemetry)</option>
                  <option value="KNOWLEDGE">KNOWLEDGE (Ingestion/Purge)</option>
                  <option value="GOVERNANCE">GOVERNANCE (Roles/Transfers)</option>
                  <option value="AUTH">AUTH (Login/Registration)</option>
                </select>
              </div>

              {/* Time Range Filter */}
              <div>
                <label className="text-[10px] font-mono text-muted uppercase block mb-1">Time Range</label>
                <select
                  value={activityTimeRange}
                  onChange={(e) => {
                    setActivityTimeRange(e.target.value as any);
                    setActivityOffset(0);
                  }}
                  className="w-full bg-paper-2 border border-rule text-ink text-xs font-mono rounded-base px-2.5 py-1.5 focus:outline-none focus:border-accent"
                >
                  <option value="all">All Time (Recorded)</option>
                  <option value="today">Today (UTC)</option>
                  <option value="7d">Last 7 Days</option>
                  <option value="30d">Last 30 Days</option>
                </select>
              </div>

              {/* User Filter */}
              <div>
                <label className="text-[10px] font-mono text-muted uppercase block mb-1">Target Member</label>
                <select
                  value={activityUserId}
                  onChange={(e) => {
                    setActivityUserId(e.target.value);
                    setActivityOffset(0);
                  }}
                  className="w-full bg-paper-2 border border-rule text-ink text-xs font-mono rounded-base px-2.5 py-1.5 focus:outline-none focus:border-accent"
                >
                  <option value="">ALL MEMBERS</option>
                  {users.map((u) => (
                    <option key={u.id} value={String(u.id)}>
                      {u.username} ({u.role})
                    </option>
                  ))}
                </select>
              </div>

              {/* Keyword Search */}
              <div>
                <label className="text-[10px] font-mono text-muted uppercase block mb-1">Keyword Search</label>
                <input
                  type="text"
                  placeholder="Filter by description or action..."
                  value={activitySearch}
                  onChange={(e) => {
                    setActivitySearch(e.target.value);
                    setActivityOffset(0);
                  }}
                  className="w-full bg-paper-2 border border-rule text-ink text-xs font-mono rounded-base px-2.5 py-1.5 focus:outline-none focus:border-accent"
                />
              </div>
            </div>

            {/* AUDIT TABLE */}
            {isLoadingActivity ? (
              <div className="border border-rule rounded-base bg-paper overflow-hidden">
                <div className="px-3.5 py-2 border-b border-rule flex items-center justify-between bg-paper-3 text-[11px] font-mono text-muted">
                  <div className="flex items-center gap-2">
                    <CyberSpinner size="xs" variant="accent" />
                    <span className="tracking-wide">STREAMING AUDIT TELEMETRY STREAM...</span>
                  </div>
                  <span>FILTER APPLIED</span>
                </div>
                <TerminalSkeleton variant="table" count={6} />
              </div>
            ) : activities.length === 0 ? (
              <div className="text-center py-10 border border-dashed border-rule rounded-base bg-paper text-muted text-xs font-mono">
                [NO_MATCHING_AUDIT_LOGS_FOUND]
              </div>
            ) : (
              <div className="overflow-x-auto border border-rule rounded-base bg-paper">
                <table className="w-full text-left border-collapse">
                  <thead>
                    <tr className="border-b border-rule bg-paper-3 text-[11px] font-mono uppercase tracking-wider text-ink">
                      <th className="p-2.5">Time (UTC)</th>
                      <th className="p-2.5">User</th>
                      <th className="p-2.5">Category</th>
                      <th className="p-2.5">Action</th>
                      <th className="p-2.5">Description</th>
                      <th className="p-2.5 text-right">Inspection</th>
                    </tr>
                  </thead>
                  <tbody className="text-xs divide-y divide-rule font-mono">
                    {activities.map((a) => (
                      <tr key={a.id} className="hover:bg-paper-2/70 transition-colors">
                        <td className="p-2.5 text-muted whitespace-nowrap text-[11px]">
                          {a.timestamp ? new Date(a.timestamp).toISOString().replace("T", " ").substring(0, 19) : "—"}
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
                        <td className="p-2.5 text-ink-secondary text-[11px] font-semibold">
                          {a.action}
                        </td>
                        <td className="p-2.5 text-ink font-body max-w-md truncate">
                          {a.description}
                        </td>
                        <td className="p-2.5 text-right">
                          {a.details ? (
                            <button
                              onClick={() => setSelectedLogDetails(a)}
                              className="px-2 py-0.5 bg-paper-3 hover:bg-paper border border-rule text-[10px] font-mono rounded text-accent hover:border-accent cursor-pointer"
                            >
                              Inspect 🔍
                            </button>
                          ) : (
                            <span className="text-muted text-[10px]">—</span>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

            {/* PAGINATION TOOLBAR */}
            <div className="flex flex-col sm:flex-row justify-between items-center gap-3 pt-2 text-xs font-mono text-muted">
              <div>
                Showing <strong className="text-ink">{activities.length}</strong> of <strong className="text-ink">{activityTotal}</strong> total audit records
              </div>
              <div className="flex items-center gap-2">
                <button
                  onClick={() => setActivityOffset(Math.max(0, activityOffset - 50))}
                  disabled={activityOffset === 0}
                  className="px-3 py-1 bg-paper border border-rule rounded text-ink disabled:opacity-40 cursor-pointer"
                >
                  ← Previous
                </button>
                <span>
                  Page {Math.floor(activityOffset / 50) + 1} of {Math.max(1, Math.ceil(activityTotal / 50))}
                </span>
                <button
                  onClick={() => setActivityOffset(activityOffset + 50)}
                  disabled={activityOffset + 50 >= activityTotal}
                  className="px-3 py-1 bg-paper border border-rule rounded text-ink disabled:opacity-40 cursor-pointer"
                >
                  Next →
                </button>
              </div>
            </div>

            {/* EVENT DETAILS MODAL */}
            {selectedLogDetails && (
              <div
                onClick={(e) => { if (e.target === e.currentTarget) setSelectedLogDetails(null); }}
                className="fixed inset-0 z-50 flex items-center justify-center p-4 sm:p-6 bg-black/75 backdrop-blur-sm animate-backdrop-fade"
              >
                <div className="bg-paper-2 border border-rule-focus rounded-card w-[94vw] max-w-2xl sm:w-[620px] p-5 sm:p-6 shadow-2xl space-y-4 my-auto relative overflow-hidden">
                  <div className="flex justify-between items-start pb-3 border-b border-rule gap-3">
                    <div>
                      <span className="text-[10px] font-mono uppercase text-muted tracking-wider block">
                        Audit Event #{selectedLogDetails.id}
                      </span>
                      <h3 className="text-base font-display font-semibold text-ink">
                        {selectedLogDetails.action}
                      </h3>
                    </div>
                    <button
                      onClick={() => setSelectedLogDetails(null)}
                      className="p-1 rounded text-muted hover:text-ink text-base cursor-pointer hover:bg-paper-3 transition-colors"
                    >
                      ✕
                    </button>
                  </div>

                  <div className="space-y-3 text-xs font-mono">
                    <div className="grid grid-cols-1 sm:grid-cols-3 gap-2 p-3 rounded-base bg-paper border border-rule">
                      <div>
                        <span className="text-muted block text-[10px] uppercase">User</span>
                        <strong className="text-ink">{selectedLogDetails.username}</strong>
                      </div>
                      <div>
                        <span className="text-muted block text-[10px] uppercase">Category</span>
                        <strong className="text-accent">{selectedLogDetails.category}</strong>
                      </div>
                      <div>
                        <span className="text-muted block text-[10px] uppercase">Timestamp (UTC)</span>
                        <span className="text-ink text-[11px] break-all">{selectedLogDetails.timestamp}</span>
                      </div>
                    </div>

                    <div>
                      <span className="text-muted block text-[10px] uppercase mb-1">Description</span>
                      <div className="p-2.5 rounded-base bg-paper border border-rule text-ink font-body leading-relaxed">
                        {selectedLogDetails.description}
                      </div>
                    </div>

                    <div>
                      <span className="text-muted block text-[10px] uppercase mb-1">Payload Metadata (JSON)</span>
                      <pre className="p-3 rounded-base bg-paper border border-rule text-emerald-400 font-mono text-[11px] overflow-x-auto max-h-56 custom-scrollbar whitespace-pre-wrap break-all">
                        {(() => {
                          try {
                            return JSON.stringify(JSON.parse(selectedLogDetails.details || "{}"), null, 2);
                          } catch {
                            return selectedLogDetails.details || "No metadata";
                          }
                        })()}
                      </pre>
                    </div>
                  </div>

                  <div className="flex justify-end pt-3 border-t border-rule">
                    <button
                      onClick={() => setSelectedLogDetails(null)}
                      className="px-4 py-2 bg-paper border border-rule hover:bg-paper-3 text-ink text-xs font-mono uppercase tracking-wider rounded-base cursor-pointer font-medium transition-colors"
                    >
                      Close Window
                    </button>
                  </div>
                </div>
              </div>
            )}
          </div>
        )}

        {/* TAB 4: SETTINGS */}
        {activeTab === "settings" && (
          <div className="space-y-6">
            {/* CORPORATE IDENTITY & SSO AUTO-ROUTING (PILLAR 8) */}
            <div className="bg-paper-2 p-5 sm:p-6 rounded-card border border-rule space-y-5">
              <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 pb-4 border-b border-rule">
                <div>
                  <div className="flex items-center gap-2 mb-1">
                    <span className="w-2 h-2 rounded-full bg-accent animate-pulse" />
                    <h2 className="text-base font-display font-semibold text-ink">
                      Corporate Identity & SSO Auto-Routing
                    </h2>
                  </div>
                  <p className="text-xs text-muted max-w-xl">
                    Configure authorized enterprise email domains. Employees signing in via Google Workspace, Microsoft 365, or GitHub using verified emails matching these domains are automatically provisioned and routed into this workspace without requiring manual join codes.
                  </p>
                </div>
                <div className="flex items-center gap-2">
                  <span className="font-mono text-[10px] uppercase tracking-wider text-muted px-2 py-0.5 rounded border border-rule bg-paper">
                    Pillar 8 SSO
                  </span>
                </div>
              </div>

              {/* Identity Providers Status Bar */}
              <div>
                <label className="text-[10px] font-mono text-muted uppercase tracking-wider block mb-2">
                  Configured Identity Providers
                </label>
                <div className="grid grid-cols-1 sm:grid-cols-3 gap-2.5">
                  <div className="flex items-center justify-between p-2.5 bg-paper rounded-base border border-rule text-xs font-mono">
                    <div className="flex items-center gap-2">
                      <svg className="w-3.5 h-3.5" viewBox="0 0 24 24">
                        <path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z" />
                        <path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" />
                        <path fill="#FBBC05" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.06H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.94l2.85-2.22.81-.63z" />
                        <path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.06l3.66 2.84c.87-2.6 3.3-4.52 6.16-4.52z" />
                      </svg>
                      <span className="text-ink">Google</span>
                    </div>
                    <span className={`px-2 py-0.5 rounded text-[10px] font-bold uppercase ${
                      oauthProviders.google
                        ? "bg-emerald-500/10 text-emerald-400 border border-emerald-500/30"
                        : "bg-paper-3 text-muted border border-rule"
                    }`}>
                      {oauthProviders.google ? "Active" : "Unconfigured"}
                    </span>
                  </div>

                  <div className="flex items-center justify-between p-2.5 bg-paper rounded-base border border-rule text-xs font-mono">
                    <div className="flex items-center gap-2">
                      <svg className="w-3.5 h-3.5" viewBox="0 0 23 23">
                        <path fill="#f35325" d="M1 1h10v10H1z" />
                        <path fill="#81bc06" d="M12 1h10v10H12z" />
                        <path fill="#05a6f0" d="M1 12h10v10H1z" />
                        <path fill="#ffba08" d="M12 12h10v10H12z" />
                      </svg>
                      <span className="text-ink">Microsoft 365</span>
                    </div>
                    <span className={`px-2 py-0.5 rounded text-[10px] font-bold uppercase ${
                      oauthProviders.microsoft
                        ? "bg-emerald-500/10 text-emerald-400 border border-emerald-500/30"
                        : "bg-paper-3 text-muted border border-rule"
                    }`}>
                      {oauthProviders.microsoft ? "Active" : "Unconfigured"}
                    </span>
                  </div>

                  <div className="flex items-center justify-between p-2.5 bg-paper rounded-base border border-rule text-xs font-mono">
                    <div className="flex items-center gap-2">
                      <svg className="w-3.5 h-3.5 fill-current text-ink" viewBox="0 0 24 24">
                        <path fillRule="evenodd" clipRule="evenodd" d="M12 2C6.477 2 2 6.484 2 12.017c0 4.425 2.865 8.18 6.839 9.504.5.092.682-.217.682-.483 0-.237-.008-.868-.013-1.703-2.782.605-3.369-1.343-3.369-1.343-.454-1.158-1.11-1.466-1.11-1.466-.908-.62.069-.608.069-.608 1.003.07 1.53 1.032 1.53 1.032.892 1.53 2.341 1.088 2.91.832.092-.647.35-1.088.636-1.338-2.22-.253-4.555-1.113-4.555-4.951 0-1.093.39-1.988 1.029-2.688-.103-.253-.446-1.272.098-2.65 0 0 .84-.27 2.75 1.026A9.564 9.564 0 0112 6.844c.85.004 1.705.115 2.504.337 1.909-1.296 2.747-1.027 2.747-1.027.546 1.379.202 2.398.1 2.651.64.7 1.028 1.595 1.028 2.688 0 3.848-2.339 4.695-4.566 4.943.359.309.678.92.678 1.855 0 1.338-.012 2.419-.012 2.747 0 .268.18.58.688.482A10.019 10.019 0 0022 12.017C22 6.484 17.522 2 12 2z" />
                      </svg>
                      <span className="text-ink">GitHub</span>
                    </div>
                    <span className={`px-2 py-0.5 rounded text-[10px] font-bold uppercase ${
                      oauthProviders.github
                        ? "bg-emerald-500/10 text-emerald-400 border border-emerald-500/30"
                        : "bg-paper-3 text-muted border border-rule"
                    }`}>
                      {oauthProviders.github ? "Active" : "Unconfigured"}
                    </span>
                  </div>
                </div>
              </div>

              {/* Active Domains Pills */}
              <div>
                <label className="text-[10px] font-mono text-muted uppercase tracking-wider block mb-1.5">
                  Currently Enforced Domain Route(s)
                </label>
                <div className="flex flex-wrap gap-2">
                  {allowedDomains ? (
                    allowedDomains.split(",").map((dom) => (
                      <span
                        key={dom.trim()}
                        className="inline-flex items-center gap-1.5 px-3 py-1 rounded-base bg-paper border border-accent/40 text-accent font-mono text-xs font-semibold shadow-xs"
                      >
                        <span className="w-1.5 h-1.5 rounded-full bg-accent" />
                        @{dom.trim()}
                      </span>
                    ))
                  ) : (
                    <span className="text-xs font-mono text-muted italic">
                      [NO_DOMAINS_RESTRICTED: Members onboarding requires secret join-code]
                    </span>
                  )}
                </div>
              </div>

              {/* Feedback messages */}
              {domainFeedback && (
                <div
                  className={`p-3 rounded-base text-xs font-mono flex items-start gap-2 ${
                    domainFeedback.type === "success"
                      ? "bg-emerald-500/10 border border-emerald-500/30 text-emerald-400"
                      : "bg-ruby-subtle border border-ruby/30 text-ruby"
                  }`}
                >
                  <span className="font-bold">[{domainFeedback.type.toUpperCase()}]</span>
                  <span>{domainFeedback.msg}</span>
                </div>
              )}

              {/* Form Input */}
              <form onSubmit={handleSaveDomains} className="space-y-3">
                <div>
                  <label className="text-[10px] font-mono text-muted uppercase tracking-wider block mb-1">
                    Allowed Corporate Email Domains (comma-separated)
                  </label>
                  <input
                    type="text"
                    placeholder="e.g. acme.com, engineering.acme.com, enterprise.org"
                    value={domainInput}
                    onChange={(e) => setDomainInput(e.target.value)}
                    className="w-full p-2.5 bg-paper border border-rule rounded-base text-ink font-mono text-xs focus:outline-none focus:border-accent"
                  />
                  <span className="text-[11px] text-muted block mt-1 font-body">
                    Public consumer email domains (e.g. gmail.com, yahoo.com) are rejected automatically for security.
                  </span>
                </div>

                <div className="flex justify-end">
                  <button
                    type="submit"
                    disabled={isSavingDomains}
                    className="px-4 py-2 bg-accent hover:bg-accent-hover text-accent-ink text-xs font-mono uppercase tracking-wider font-semibold rounded-base transition-colors cursor-pointer disabled:opacity-50 flex items-center gap-2"
                  >
                    {isSavingDomains ? (
                      <>
                        <CyberSpinner size="xs" variant="accent" />
                        <span>Updating Domains...</span>
                      </>
                    ) : (
                      <span>Save Corporate Domains ✓</span>
                    )}
                  </button>
                </div>
              </form>
            </div>

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

        {/* TAB 6: SSO & DIRECTORY SYNC (PHASE 12) */}
        {activeTab === "sso" && (
          <div className="space-y-6">
            {/* Header Landmark */}
            <div className="bg-paper-2 p-5 sm:p-6 rounded-card border border-rule">
              <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4 pb-4 mb-4 border-b border-rule">
                <div>
                  <div className="flex items-center gap-2 mb-1">
                    <span className="w-2 h-2 rounded-full bg-accent animate-pulse" />
                    <span className="font-mono text-xs uppercase tracking-wider text-muted font-medium">
                      Enterprise Identity & Single Sign-On
                    </span>
                  </div>
                  <h2 className="text-base sm:text-lg font-display font-semibold text-ink">
                    SAML 2.0 & OIDC Directory Sync
                  </h2>
                </div>
                <div className="flex items-center gap-2">
                  {ssoConfig.configured ? (
                    <span className={`font-mono text-[11px] px-2.5 py-1 rounded border uppercase font-semibold ${
                      ssoConfig.is_enabled
                        ? "bg-emerald-500/10 border-emerald-500/40 text-emerald-500"
                        : "bg-amber-500/10 border-amber-500/40 text-amber-500"
                    }`}>
                      {ssoConfig.is_enabled ? "● SSO Active" : "○ SSO Disabled"}
                    </span>
                  ) : (
                    <span className="font-mono text-[11px] px-2.5 py-1 rounded border border-rule bg-paper text-muted uppercase">
                      Not Configured
                    </span>
                  )}
                  {ssoConfig.enforce_sso && (
                    <span className="font-mono text-[11px] px-2.5 py-1 rounded border border-accent/40 bg-accent-subtle text-accent uppercase font-semibold">
                      Enforced
                    </span>
                  )}
                </div>
              </div>

              <p className="text-xs text-muted leading-relaxed">
                Federate authentication with your corporate Identity Provider (Okta, Microsoft Entra ID, Google Workspace, PingFederate).
                Users can authenticate seamlessly via work email auto-discovery and automatically inherit RBAC roles from corporate directory group claims.
              </p>

              {ssoFeedback && (
                <div className={`mt-4 p-3 rounded-base text-xs font-mono border ${
                  ssoFeedback.type === "success"
                    ? "bg-emerald-500/10 border-emerald-500/30 text-emerald-500"
                    : "bg-ruby-subtle border-ruby/30 text-ruby"
                }`}>
                  [{ssoFeedback.type.toUpperCase()}] {ssoFeedback.msg}
                </div>
              )}
            </div>

            {isLoadingSso ? (
              <div className="bg-paper-2 p-8 rounded-card border border-rule flex flex-col items-center justify-center">
                <CyberSpinner size="lg" variant="accent" label="Loading Single Sign-On configuration..." />
              </div>
            ) : (
              <form onSubmit={handleSaveSSOConfig} className="space-y-6">
                {/* Protocol & Enforcement Settings */}
                <div className="bg-paper-2 p-5 sm:p-6 rounded-card border border-rule space-y-4">
                  <h3 className="text-xs font-mono uppercase tracking-wider text-muted font-semibold pb-2 border-b border-rule">
                    1. Identity Provider Protocol & Enforcement
                  </h3>

                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                    <div>
                      <label className="block font-mono text-[11px] uppercase tracking-wider text-muted mb-1.5">
                        Protocol Architecture
                      </label>
                      <select
                        value={ssoConfig.idp_type}
                        onChange={(e) => setSsoConfig({ ...ssoConfig, idp_type: e.target.value })}
                        className="w-full bg-paper border border-rule focus:border-accent focus:outline-none rounded-base py-2 px-3 text-xs text-ink font-body"
                      >
                        <option value="saml">SAML 2.0 (Okta, Entra ID, PingFederate, Shibboleth)</option>
                        <option value="oidc">Enterprise OIDC (Okta, Google Workspace, Keycloak, Auth0)</option>
                      </select>
                    </div>

                    <div>
                      <label className="block font-mono text-[11px] uppercase tracking-wider text-muted mb-1.5">
                        Corporate Domains (Routing)
                      </label>
                      <input
                        type="text"
                        value={ssoConfig.allowed_domains}
                        onChange={(e) => setSsoConfig({ ...ssoConfig, allowed_domains: e.target.value })}
                        placeholder="e.g. acme.com, corp.acme.com"
                        className="w-full bg-paper border border-rule focus:border-accent focus:outline-none rounded-base py-2 px-3 text-xs text-ink font-mono"
                      />
                      <span className="text-[10px] text-muted font-mono mt-1 block">
                        Work emails matching these domains route directly to your IdP.
                      </span>
                    </div>
                  </div>

                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 pt-2">
                    <label className="flex items-start gap-3 p-3 bg-paper rounded-base border border-rule cursor-pointer hover:border-rule-strong">
                      <input
                        type="checkbox"
                        checked={ssoConfig.is_enabled}
                        onChange={(e) => setSsoConfig({ ...ssoConfig, is_enabled: e.target.checked })}
                        className="mt-0.5 accent-accent"
                      />
                      <div>
                        <span className="font-mono text-xs uppercase tracking-wider font-semibold text-ink block">
                          Enable Single Sign-On
                        </span>
                        <span className="text-[11px] text-muted block mt-0.5">
                          Allows members to authenticate using enterprise SSO credentials.
                        </span>
                      </div>
                    </label>

                    <label className="flex items-start gap-3 p-3 bg-paper rounded-base border border-rule cursor-pointer hover:border-rule-strong">
                      <input
                        type="checkbox"
                        checked={ssoConfig.enforce_sso}
                        onChange={(e) => setSsoConfig({ ...ssoConfig, enforce_sso: e.target.checked })}
                        className="mt-0.5 accent-accent"
                      />
                      <div>
                        <span className="font-mono text-xs uppercase tracking-wider font-semibold text-ink block">
                          Enforce SSO (Strict Mode)
                        </span>
                        <span className="text-[11px] text-muted block mt-0.5">
                          Disables standard password login for users in your organization.
                        </span>
                      </div>
                    </label>
                  </div>
                </div>

                {/* Service Provider (SP) Metadata Box (Always shown for reference) */}
                <div className="bg-paper-2 p-5 sm:p-6 rounded-card border border-rule space-y-4">
                  <div className="flex justify-between items-center pb-2 border-b border-rule">
                    <h3 className="text-xs font-mono uppercase tracking-wider text-muted font-semibold">
                      2. Service Provider (SP) Metadata
                    </h3>
                    <span className="text-[10px] font-mono text-muted uppercase">Copy into your IdP</span>
                  </div>

                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 font-mono text-xs">
                    <div>
                      <span className="text-[10px] uppercase text-muted block mb-1">Entity ID / Audience URI</span>
                      <div className="flex items-center gap-2 bg-paper p-2 rounded-base border border-rule">
                        <span className="truncate text-ink">{ssoConfig.sp_entity_id || `${API_URL}/auth/sso/saml/metadata`}</span>
                        <button
                          type="button"
                          onClick={() => copyToClipboard(ssoConfig.sp_entity_id || `${API_URL}/auth/sso/saml/metadata`, "entity_id")}
                          className="shrink-0 text-[10px] text-accent uppercase font-bold hover:underline cursor-pointer"
                        >
                          {ssoCopiedItem === "entity_id" ? "Copied!" : "Copy"}
                        </button>
                      </div>
                    </div>

                    <div>
                      <span className="text-[10px] uppercase text-muted block mb-1">
                        {ssoConfig.idp_type === "saml" ? "ACS URL (Assertion Consumer)" : "OIDC Redirect Callback URI"}
                      </span>
                      <div className="flex items-center gap-2 bg-paper p-2 rounded-base border border-rule">
                        <span className="truncate text-ink">
                          {ssoConfig.idp_type === "saml"
                            ? (ssoConfig.sp_acs_url || `${API_URL}/auth/sso/saml/acs`)
                            : (typeof window !== "undefined" ? `${window.location.origin}/auth/callback?provider=oidc` : "")}
                        </span>
                        <button
                          type="button"
                          onClick={() => copyToClipboard(
                            ssoConfig.idp_type === "saml"
                              ? (ssoConfig.sp_acs_url || `${API_URL}/auth/sso/saml/acs`)
                              : `${window.location.origin}/auth/callback?provider=oidc`,
                            "acs_url"
                          )}
                          className="shrink-0 text-[10px] text-accent uppercase font-bold hover:underline cursor-pointer"
                        >
                          {ssoCopiedItem === "acs_url" ? "Copied!" : "Copy"}
                        </button>
                      </div>
                    </div>
                  </div>

                  {ssoConfig.idp_type === "saml" && (
                    <div className="pt-2 flex items-center justify-between text-xs font-mono">
                      <span className="text-muted">Direct SP Metadata XML Endpoint:</span>
                      <a
                        href={`${API_URL}/auth/sso/saml/metadata`}
                        target="_blank"
                        rel="noreferrer"
                        className="text-accent hover:underline flex items-center gap-1 font-semibold"
                      >
                        <span>View / Download SP Metadata XML →</span>
                      </a>
                    </div>
                  )}
                </div>

                {/* Identity Provider Details */}
                {ssoConfig.idp_type === "saml" ? (
                  <div className="bg-paper-2 p-5 sm:p-6 rounded-card border border-rule space-y-4">
                    <h3 className="text-xs font-mono uppercase tracking-wider text-muted font-semibold pb-2 border-b border-rule">
                      3. SAML 2.0 Identity Provider (IdP) Configuration
                    </h3>

                    {/* Quick Metadata XML Parser */}
                    <div>
                      <div className="flex justify-between items-center mb-1.5">
                        <label className="block font-mono text-[11px] uppercase tracking-wider text-muted">
                          Fast Track: Paste IdP Metadata XML
                        </label>
                        <span className="text-[10px] font-mono text-emerald-500 uppercase">Auto-extracts certificates & endpoints</span>
                      </div>
                      <textarea
                        value={ssoConfig.idp_metadata_xml}
                        onChange={(e) => setSsoConfig({ ...ssoConfig, idp_metadata_xml: e.target.value })}
                        rows={4}
                        placeholder='<EntityDescriptor xmlns="urn:oasis:names:tc:SAML:2.0:metadata" entityID="https://idp.example.com">...'
                        className="w-full bg-paper border border-rule focus:border-accent focus:outline-none rounded-base py-2 px-3 text-xs text-ink font-mono"
                      />
                    </div>

                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                      <div>
                        <label className="block font-mono text-[11px] uppercase tracking-wider text-muted mb-1.5">
                          IdP Entity ID (Issuer URI)
                        </label>
                        <input
                          type="text"
                          value={ssoConfig.idp_entity_id}
                          onChange={(e) => setSsoConfig({ ...ssoConfig, idp_entity_id: e.target.value })}
                          placeholder="https://www.okta.com/exk123456"
                          className="w-full bg-paper border border-rule focus:border-accent focus:outline-none rounded-base py-2 px-3 text-xs text-ink font-mono"
                        />
                      </div>

                      <div>
                        <label className="block font-mono text-[11px] uppercase tracking-wider text-muted mb-1.5">
                          IdP SingleSignOnService URL
                        </label>
                        <input
                          type="text"
                          value={ssoConfig.idp_sso_url}
                          onChange={(e) => setSsoConfig({ ...ssoConfig, idp_sso_url: e.target.value })}
                          placeholder="https://dev-123.okta.com/app/app_name/sso/saml"
                          className="w-full bg-paper border border-rule focus:border-accent focus:outline-none rounded-base py-2 px-3 text-xs text-ink font-mono"
                        />
                      </div>
                    </div>

                    <div>
                      <label className="block font-mono text-[11px] uppercase tracking-wider text-muted mb-1.5">
                        IdP Public X.509 Certificate (PEM)
                      </label>
                      <textarea
                        value={ssoConfig.idp_x509_cert}
                        onChange={(e) => setSsoConfig({ ...ssoConfig, idp_x509_cert: e.target.value })}
                        rows={4}
                        placeholder="-----BEGIN CERTIFICATE-----&#10;MIIDpDCCAoygAwIBAgIGAX...&#10;-----END CERTIFICATE-----"
                        className="w-full bg-paper border border-rule focus:border-accent focus:outline-none rounded-base py-2 px-3 text-xs text-ink font-mono"
                      />
                    </div>
                  </div>
                ) : (
                  <div className="bg-paper-2 p-5 sm:p-6 rounded-card border border-rule space-y-4">
                    <h3 className="text-xs font-mono uppercase tracking-wider text-muted font-semibold pb-2 border-b border-rule">
                      3. Enterprise OIDC Configuration
                    </h3>

                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                      <div>
                        <label className="block font-mono text-[11px] uppercase tracking-wider text-muted mb-1.5">
                          OIDC Issuer URL (Discovery)
                        </label>
                        <input
                          type="text"
                          value={ssoConfig.oidc_issuer_url}
                          onChange={(e) => setSsoConfig({ ...ssoConfig, oidc_issuer_url: e.target.value })}
                          placeholder="https://dev-123.okta.com or https://accounts.google.com"
                          className="w-full bg-paper border border-rule focus:border-accent focus:outline-none rounded-base py-2 px-3 text-xs text-ink font-mono"
                        />
                      </div>

                      <div>
                        <label className="block font-mono text-[11px] uppercase tracking-wider text-muted mb-1.5">
                          OIDC Scopes
                        </label>
                        <input
                          type="text"
                          value={ssoConfig.oidc_scopes}
                          onChange={(e) => setSsoConfig({ ...ssoConfig, oidc_scopes: e.target.value })}
                          placeholder="openid email profile groups"
                          className="w-full bg-paper border border-rule focus:border-accent focus:outline-none rounded-base py-2 px-3 text-xs text-ink font-mono"
                        />
                      </div>

                      <div>
                        <label className="block font-mono text-[11px] uppercase tracking-wider text-muted mb-1.5">
                          Client ID
                        </label>
                        <input
                          type="text"
                          value={ssoConfig.oidc_client_id}
                          onChange={(e) => setSsoConfig({ ...ssoConfig, oidc_client_id: e.target.value })}
                          placeholder="0oa1234567890abcdef"
                          className="w-full bg-paper border border-rule focus:border-accent focus:outline-none rounded-base py-2 px-3 text-xs text-ink font-mono"
                        />
                      </div>

                      <div>
                        <label className="block font-mono text-[11px] uppercase tracking-wider text-muted mb-1.5">
                          Client Secret
                        </label>
                        <input
                          type="password"
                          value={ssoConfig.oidc_client_secret}
                          onChange={(e) => setSsoConfig({ ...ssoConfig, oidc_client_secret: e.target.value })}
                          placeholder="••••••••••••••••"
                          className="w-full bg-paper border border-rule focus:border-accent focus:outline-none rounded-base py-2 px-3 text-xs text-ink font-mono"
                        />
                      </div>
                    </div>
                  </div>
                )}

                {/* Directory Role Mapping & Provisioning */}
                <div className="bg-paper-2 p-5 sm:p-6 rounded-card border border-rule space-y-4">
                  <h3 className="text-xs font-mono uppercase tracking-wider text-muted font-semibold pb-2 border-b border-rule">
                    4. Directory Group to RBAC Role Sync
                  </h3>

                  <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
                    <div>
                      <label className="block font-mono text-[11px] uppercase tracking-wider text-muted mb-1.5">
                        Default Fallback Role
                      </label>
                      <select
                        value={ssoConfig.default_role}
                        onChange={(e) => setSsoConfig({ ...ssoConfig, default_role: e.target.value })}
                        className="w-full bg-paper border border-rule focus:border-accent focus:outline-none rounded-base py-2 px-3 text-xs text-ink font-body"
                      >
                        <option value="user">User (Read-only + Chat)</option>
                        <option value="editor">Editor (Upload + Knowledge Corpus)</option>
                        <option value="admin">Admin (Corpus + Tenant Settings)</option>
                      </select>
                      <span className="text-[10px] text-muted font-mono mt-1 block">
                        Assigned when no directory group match is resolved.
                      </span>
                    </div>

                    <div className="sm:col-span-2">
                      <div className="flex justify-between items-center mb-1.5">
                        <label className="block font-mono text-[11px] uppercase tracking-wider text-muted">
                          Corporate Group Mapping (JSON)
                        </label>
                        <span className="text-[10px] font-mono text-muted">IdP Group Claim → Role</span>
                      </div>
                      <textarea
                        value={ssoConfig.role_mapping_json}
                        onChange={(e) => setSsoConfig({ ...ssoConfig, role_mapping_json: e.target.value })}
                        rows={4}
                        placeholder='{"Security-Engineers": "admin", "Technical-Writers": "editor"}'
                        className="w-full bg-paper border border-rule focus:border-accent focus:outline-none rounded-base py-2 px-3 text-xs text-ink font-mono"
                      />
                    </div>
                  </div>
                </div>

                {/* Session Security & Emergency Revocation */}
                <div className="bg-paper-2 p-5 sm:p-6 rounded-card border border-ruby/30 space-y-3">
                  <div className="flex items-center gap-2">
                    <span className="w-2 h-2 rounded-full bg-ruby animate-pulse" />
                    <h3 className="text-xs font-mono uppercase tracking-wider text-ruby font-semibold">
                      5. Emergency Session Invalidation & Token Revocation
                    </h3>
                  </div>
                  <p className="text-xs text-muted">
                    If an employee leaves or credentials are compromised, immediately invalidate all active JWT tokens in Redis.
                    All users in your organization will be logged out on their next request.
                  </p>
                  <button
                    type="button"
                    onClick={handleRevokeAllSessions}
                    disabled={isRevokingSessions}
                    className="py-2 px-4 rounded-base bg-ruby-subtle border border-ruby/40 text-ruby hover:bg-ruby hover:text-white text-xs font-mono uppercase tracking-wider font-semibold transition-all cursor-pointer disabled:opacity-50"
                  >
                    {isRevokingSessions ? "Revoking Active Sessions..." : "⚠️ Revoke All Active Organization Sessions"}
                  </button>
                </div>

                {/* Form Actions */}
                <div className="flex flex-col sm:flex-row justify-between items-center gap-3 pt-4 border-t border-rule">
                  {ssoConfig.configured ? (
                    <button
                      type="button"
                      onClick={handleDeleteSSOConfig}
                      disabled={isSavingSso}
                      className="w-full sm:w-auto py-2.5 px-4 rounded-base border border-ruby/40 text-ruby hover:bg-ruby-subtle text-xs font-mono uppercase tracking-wider font-semibold transition-all cursor-pointer disabled:opacity-50"
                    >
                      Delete SSO Configuration
                    </button>
                  ) : <div />}

                  <button
                    type="submit"
                    disabled={isSavingSso}
                    className="w-full sm:w-auto py-2.5 px-6 rounded-base bg-accent hover:bg-accent-hover text-accent-ink text-xs font-mono uppercase tracking-wider font-semibold transition-all cursor-pointer disabled:opacity-50 flex items-center justify-center gap-2 shadow-sm"
                  >
                    {isSavingSso ? (
                      <CyberSpinner size="sm" variant="ink" label="Saving..." />
                    ) : (
                      "Save SSO Configuration →"
                    )}
                  </button>
                </div>
              </form>
            )}
          </div>
        )}

      </div>
    </div>
  );
}
