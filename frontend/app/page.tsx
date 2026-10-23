"use client";

import { useState, useRef, useEffect } from "react";
import { useRouter } from "next/navigation";
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter';
import { vscDarkPlus } from 'react-syntax-highlighter/dist/esm/styles/prism';
import toast from 'react-hot-toast';

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://192.168.1.92:8000";

type Message = {
  role: "user" | "assistant";
  content: string;
};

type Session = {
  id: number;
  title: string;
  created_at: string;
};

export default function Home() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [documents, setDocuments] = useState<string[]>([]);
  const [globalDocuments, setGlobalDocuments] = useState<string[]>([]);
  const [sessions, setSessions] = useState<Session[]>([]);
  const [activeSessionId, setActiveSessionId] = useState<number | null>(null);
  const [userRole, setUserRole] = useState<string>("user");
  const [username, setUsername] = useState<string>("");
  const [tenantName, setTenantName] = useState<string>("");
  const [isPlatformAdmin, setIsPlatformAdmin] = useState<boolean>(false);
  const [pendingRequest, setPendingRequest] = useState<string | null>(null);
  const [incomingTransfer, setIncomingTransfer] = useState<{ id: number; from_username: string } | null>(null);
  const [isRequestingRole, setIsRequestingRole] = useState(false);
  const [activeDocTab, setActiveDocTab] = useState<"personal" | "global">("personal");
  
  const [isUploading, setIsUploading] = useState(false);
  const [isTyping, setIsTyping] = useState(false);
  
  // Mention menu states (@ and !)
  const [showMentionMenu, setShowMentionMenu] = useState(false);
  const [mentionQuery, setMentionQuery] = useState("");
  const [mentionPrefix, setMentionPrefix] = useState<"@" | "!">("@");
  const [mentionIndex, setMentionIndex] = useState(0);
  
  const fileInputRef = useRef<HTMLInputElement>(null);
  const globalFileInputRef = useRef<HTMLInputElement>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const router = useRouter();

  // Authenticated fetch helper
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
    try {
      const res = await fetch(url, { ...options, headers });
      if (res.status === 401) {
        localStorage.removeItem("token");
        router.push("/login");
        throw new Error("Unauthorized");
      }
      return res;
    } catch (err: unknown) {
      if (err instanceof TypeError && err.message.includes('Failed to fetch')) {
        toast.error("Network error: Cannot connect to backend server.");
      }
      throw err;
    }
  };

  const fetchDocuments = async () => {
    try {
      const res = await authFetch(`${API_URL}/documents`);
      if (res.ok) {
        const data = await res.json();
        setDocuments(data.documents || []);
        setGlobalDocuments(data.global_documents || []);
      }
    } catch (error) {
      console.error("Failed to fetch documents:", error);
    }
  };

  const fetchMe = async () => {
    try {
      const res = await authFetch(`${API_URL}/auth/me`);
      if (res.ok) {
        const data = await res.json();
        if (data.access_token) {
          localStorage.setItem("token", data.access_token);
        }
        setUserRole(data.role || "user");
        if (data.role) localStorage.setItem("role", data.role);
        setUsername(data.username || "");
        setTenantName(data.tenant_name || "");
        setIsPlatformAdmin(Boolean(data.is_platform_admin));
      }
      
      const reqRes = await authFetch(`${API_URL}/auth/my_request`);
      if (reqRes.ok) {
        const reqData = await reqRes.json();
        if (reqData) {
          setPendingRequest(reqData.status === "pending" ? reqData.requested_role : null);
        }
      }

      // Check for incoming SuperAdmin ownership transfer
      try {
        const trRes = await authFetch(`${API_URL}/admin/pending_transfers`);
        if (trRes.ok) {
          const transfers = await trRes.json();
          const incoming = transfers.find((t: any) => t.is_recipient);
          setIncomingTransfer(incoming || null);
        }
      } catch {
        // Non-fatal if transfer check fails
      }
    } catch (error) {
      console.error("Failed to fetch user profile:", error);
    }
  };

  const fetchSessions = async () => {
    try {
      const res = await authFetch(`${API_URL}/sessions`);
      if (res.ok) {
        const data = await res.json();
        setSessions(data || []);
        if (data.length > 0 && activeSessionId === null) {
          setActiveSessionId(data[0].id);
        } else if (data.length === 0) {
          handleNewChat();
        }
      }
    } catch (error) {
      console.error("Failed to fetch sessions:", error);
    }
  };

  const fetchMessages = async (sessionId: number) => {
    try {
      const res = await authFetch(`${API_URL}/sessions/${sessionId}/messages`);
      if (res.ok) {
        const data = await res.json();
        setMessages(data || []);
      }
    } catch (error) {
      console.error("Failed to fetch messages:", error);
    }
  };


  const handleNewChat = async () => {
    try {
      const res = await authFetch(`${API_URL}/sessions`, {
        method: "POST",
      });
      if (res.ok) {
        const newSession = await res.json();
        await fetchSessions();
        setActiveSessionId(newSession.id);
        setTimeout(() => inputRef.current?.focus(), 100);
      }
    } catch (error) {
      console.error("Failed to create new chat:", error);
    }
  };

  const handleDeleteSession = async (sessionId: number, e: React.MouseEvent) => {
    e.stopPropagation();
    try {
      const res = await authFetch(`${API_URL}/sessions/${sessionId}`, {
        method: "DELETE",
      });
      if (res.ok) {
        toast.success("Session deleted");
        if (activeSessionId === sessionId) {
          setActiveSessionId(null);
        }
        await fetchSessions();
      }
    } catch (error) {
      console.error("Delete session error:", error);
    }
  };

  const handleUpdateSessionTitle = async (sessionId: number, newTitle: string) => {
    try {
      await authFetch(`${API_URL}/sessions/${sessionId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title: newTitle }),
      });
      fetchSessions();
    } catch (error) {
      console.error("Update title error:", error);
    }
  };

  const handleUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    setIsUploading(true);
    const formData = new FormData();
    formData.append("file", file);

    try {
      const res = await authFetch(`${API_URL}/upload`, {
        method: "POST",
        body: formData,
      });

      if (res.ok) {
        const data = await res.json();
        const taskId = data.task_id;
        if (taskId) {
          toast.loading("Indexing document chunks in Celery worker...", { id: "upload-task" });
          let attempts = 0;
          const pollInterval = setInterval(async () => {
            attempts++;
            try {
              const statusRes = await authFetch(`${API_URL}/tasks/${taskId}`);
              if (statusRes.ok) {
                const statusData = await statusRes.json();
                if (statusData.ready) {
                  clearInterval(pollInterval);
                  if (statusData.successful) {
                    toast.success("Document ingested and vector indexed!", { id: "upload-task" });
                  } else {
                    toast.error(`Ingestion error: ${statusData.result || "Worker fault"}`, { id: "upload-task" });
                  }
                  await fetchDocuments();
                }
              }
            } catch {
              // continue polling
            }
            if (attempts > 30) {
              clearInterval(pollInterval);
              toast.error("Upload worker timed out", { id: "upload-task" });
              await fetchDocuments();
            }
          }, 1500);
        } else {
          toast.success("Document uploaded successfully");
          await fetchDocuments();
        }
      } else {
        const err = await res.json();
        toast.error(`Upload rejected: ${err.detail}`);
      }
    } catch (error) {
      console.error("Upload error:", error);
      toast.error("Failed to connect to backend for upload.");
    } finally {
      setIsUploading(false);
      if (fileInputRef.current) {
        fileInputRef.current.value = "";
      }
    }
  };

  const handleGlobalUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
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
        toast.success("Global document ingested successfully");
        await fetchDocuments();
      } else {
        const err = await res.json();
        toast.error(`Global upload failed: ${err.detail}`);
      }
    } catch (error) {
      console.error("Upload error:", error);
      toast.error("Failed to connect to backend for global upload.");
    } finally {
      setIsUploading(false);
      if (globalFileInputRef.current) {
        globalFileInputRef.current.value = "";
      }
    }
  };

  const handleRoleRequest = async (role: string) => {
    try {
      const res = await authFetch(`${API_URL}/auth/request_role`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ role }),
      });
      if (res.ok) {
        setPendingRequest(role);
        setIsRequestingRole(false);
        toast.success(`Access request for ${role.toUpperCase()} submitted.`);
      } else {
        const err = await res.json();
        toast.error(`Request rejected: ${err.detail}`);
      }
    } catch (error) {
      console.error("Role request error:", error);
    }
  };

  const handleAcceptIncomingTransfer = async (transferId: number) => {
    try {
      const res = await authFetch(`${API_URL}/admin/accept_transfer/${transferId}`, { method: "POST" });
      if (res.ok) {
        toast.success("Congratulations! You are now the SuperAdmin / Owner.");
        setIncomingTransfer(null);
        await fetchMe();
      } else {
        const err = await res.json();
        toast.error(`Transfer failed: ${err.detail}`);
      }
    } catch (e) {
      console.error(e);
    }
  };

  const handleRejectIncomingTransfer = async (transferId: number) => {
    try {
      const res = await authFetch(`${API_URL}/admin/reject_transfer/${transferId}`, { method: "POST" });
      if (res.ok) {
        toast.success("Transfer offer declined.");
        setIncomingTransfer(null);
      }
    } catch (e) {
      console.error(e);
    }
  };

  const handleDeleteDoc = async (filename: string, e: React.MouseEvent) => {
    e.stopPropagation();
    try {
      const res = await authFetch(`${API_URL}/documents/${encodeURIComponent(filename)}`, {
        method: "DELETE",
      });
      if (res.ok) {
        toast.success("Document removed from index");
        await fetchDocuments();
      } else {
        const err = await res.json();
        toast.error(`Deletion failed: ${err.detail || "Unknown error"}`);
      }
    } catch (error) {
      console.error("Delete error:", error);
      toast.error("Failed to connect to backend for deletion.");
    }
  };

  // Auto-scroll to bottom of chat
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, isTyping]);

  // Initial load
  useEffect(() => {
    const token = localStorage.getItem("token");
    if (!token) {
      router.push("/login");
      return;
    }
    fetchMe();
    fetchDocuments();
    fetchSessions();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // Fetch messages when active session changes
  useEffect(() => {
    if (activeSessionId !== null) {
      fetchMessages(activeSessionId);
    }
  }, [activeSessionId]); // eslint-disable-line react-hooks/exhaustive-deps

  const handleInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const val = e.target.value;
    setInput(val);

    const match = val.match(/([@!])([\w\.,_-]*)$/);
    if (match) {
      setShowMentionMenu(true);
      setMentionPrefix(match[1] as "@" | "!");
      setMentionQuery(match[2]);
      setMentionIndex(0);
    } else {
      setShowMentionMenu(false);
    }
  };

  const handleSelectMention = (doc: string) => {
    const match = input.match(/([@!])([\w\.,_-]*)$/);
    if (match) {
      const newInput = input.substring(0, match.index) + mentionPrefix + doc + " ";
      setInput(newInput);
      setShowMentionMenu(false);
      inputRef.current?.focus();
    }
  };

  const filteredDocs = [...documents, ...globalDocuments].filter(d => 
    d.toLowerCase().includes(mentionQuery.toLowerCase())
  );

  const handleSend = async (queryText?: string) => {
    const userQuery = (queryText || input).trim();
    if (!userQuery) return;
    
    let currentSessionId = activeSessionId;
    if (currentSessionId === null) {
      try {
        const res = await authFetch(`${API_URL}/sessions`, { method: "POST" });
        if (res.ok) {
          const newSession = await res.json();
          currentSessionId = newSession.id;
          setActiveSessionId(newSession.id);
          await fetchSessions();
        } else {
          return;
        }
      } catch {
        return;
      }
    }

    setInput("");
    setShowMentionMenu(false);
    
    const isFirstMessage = messages.length <= 1;
    setMessages((prev) => [...prev, { role: "user", content: userQuery }]);
    setIsTyping(true);

    // Placeholder for streaming assistant response
    setMessages((prev) => [...prev, { role: "assistant", content: "" }]);

    if (isFirstMessage && currentSessionId) {
      let generatedTitle = userQuery.split(" ").slice(0, 5).join(" ");
      if (generatedTitle.length > 32) {
        generatedTitle = generatedTitle.substring(0, 30) + "...";
      }
      handleUpdateSessionTitle(currentSessionId, generatedTitle);
    }

    try {
      const res = await authFetch(`${API_URL}/query`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query: userQuery, session_id: currentSessionId }),
      });

      if (!res.ok) {
        throw new Error("Failed to receive telemetry response");
      }

      const reader = res.body?.getReader();
      const decoder = new TextDecoder("utf-8");
      if (!reader) return;

      let assistantResponse = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        const chunk = decoder.decode(value, { stream: true });
        assistantResponse += chunk;

        setMessages((prev) => {
          const newMessages = [...prev];
          newMessages[newMessages.length - 1] = {
            role: "assistant",
            content: assistantResponse,
          };
          return newMessages;
        });
      }
    } catch (error) {
      console.error("Query error:", error);
      setMessages((prev) => {
        const newMessages = [...prev];
        newMessages[newMessages.length - 1] = {
          role: "assistant",
          content: "System alert: Error connecting to inference pipeline. Check model configuration or server status.",
        };
        return newMessages;
      });
    } finally {
      setIsTyping(false);
    }
  };

  const activeSessionTitle = sessions.find(s => s.id === activeSessionId)?.title || (activeSessionId ? `Investigation #${activeSessionId}` : "New Investigation");

  return (
    <div className="flex h-screen bg-paper text-ink overflow-hidden">
      
      {/* SIDEBAR: SESSIONS & KNOWLEDGE BASE */}
      <aside className="w-80 bg-paper-2 border-r border-rule flex flex-col z-20 shrink-0">
        
        {/* Brand & Workspace Header */}
        <div className="p-4 border-b border-rule flex items-center justify-between">
          <div className="flex items-center gap-2.5">
            <span className="w-2.5 h-2.5 rounded-full bg-accent animate-pulse" />
            <div>
              <div className="font-display font-semibold text-sm tracking-tight text-ink uppercase">
                Knowledge Engine
              </div>
              <div className="font-mono text-[10px] uppercase text-muted tracking-wider">
                Hybrid RAG + SQL Console
              </div>
            </div>
          </div>
          <button 
            onClick={handleNewChat}
            className="p-1.5 rounded-base border border-rule hover:border-accent bg-paper hover:bg-paper-3 text-ink transition-colors cursor-pointer text-xs font-mono"
            title="Start New Investigation (Ctrl+N)"
          >
            + New
          </button>
        </div>

        {/* Organization Tenant Header Badge */}
        {tenantName && (
          <div className="px-4 py-1.5 border-b border-rule bg-paper-3/40 flex items-center justify-between">
            <div className="flex items-center gap-1.5 overflow-hidden">
              <span className="text-[10px] text-muted">🏢</span>
              <span className="font-mono text-[11px] font-bold text-ink truncate" title={tenantName}>
                {tenantName}
              </span>
            </div>
            <span className="font-mono text-[9px] px-1.5 py-0.5 rounded border border-rule bg-paper text-muted uppercase font-bold shrink-0">
              {userRole === "superadmin" ? "👑 OWNER" : userRole.toUpperCase()}
            </span>
          </div>
        )}

        {/* User Identity / Access Control Bar */}
        <div className="px-4 py-2 border-b border-rule bg-paper flex items-center justify-between text-xs">
          <div className="flex items-center gap-1.5 overflow-hidden">
            <span className="w-1.5 h-1.5 rounded-full bg-emerald-500" />
            <span className="truncate text-ink-secondary font-medium" title={username}>
              {username || "Analyst"}
            </span>
          </div>

          <div className="flex items-center gap-1.5 shrink-0">
            {isPlatformAdmin && (
              <button
                onClick={() => router.push("/platform-admin")}
                className="font-mono text-[10px] px-2 py-0.5 rounded border border-accent bg-accent-subtle text-accent font-bold transition-colors cursor-pointer"
                title="Platform SuperAdmin Dashboard"
              >
                🌐 Global
              </button>
            )}
            {(userRole === "admin" || userRole === "superadmin") && (
              <button
                onClick={() => router.push("/admin")}
                className="font-mono text-[11px] px-2 py-0.5 rounded border border-rule hover:border-accent text-ink transition-colors cursor-pointer"
              >
                Admin
              </button>
            )}
            {userRole === "user" && !pendingRequest && (
              <button
                onClick={() => setIsRequestingRole(true)}
                className="font-mono text-[11px] px-2 py-0.5 rounded border border-rule hover:border-accent text-accent transition-colors cursor-pointer"
              >
                Request Role
              </button>
            )}
            {pendingRequest && (
              <span className="font-mono text-[10px] px-1.5 py-0.5 rounded border border-rule text-muted">
                {pendingRequest} req
              </span>
            )}
            <button
              onClick={() => {
                localStorage.removeItem("token");
                localStorage.removeItem("role");
                localStorage.removeItem("tenant_name");
                localStorage.removeItem("is_platform_admin");
                router.push("/login");
              }}
              className="text-muted hover:text-ruby p-1 transition-colors cursor-pointer"
              title="Terminate Session"
            >
              <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17 16l4-4m0 0l-4-4m4 4H7m6 4v1a3 3 0 01-3 3H6a3 3 0 01-3-3V7a3 3 0 013-3h4a3 3 0 013 3v1" />
              </svg>
            </button>
          </div>
        </div>

        {/* SESSIONS HISTORY SECTION */}
        <div className="flex-1 min-h-[160px] overflow-y-auto p-3 custom-scrollbar border-b border-rule">
          <div className="flex items-center justify-between mb-2 px-1">
            <span className="font-mono text-[11px] uppercase tracking-wider text-muted font-medium">
              Investigations ({sessions.length})
            </span>
          </div>

          {sessions.length === 0 ? (
            <div className="text-center py-6 border border-dashed border-rule rounded-base text-muted text-xs font-mono">
              [NO_ACTIVE_INVESTIGATIONS]
            </div>
          ) : (
            <div className="space-y-1">
              {sessions.map((session) => (
                <div
                  key={session.id}
                  onClick={() => setActiveSessionId(session.id)}
                  className={`group relative flex items-center justify-between px-3 py-2 rounded-base cursor-pointer transition-colors text-xs ${
                    activeSessionId === session.id
                      ? "bg-accent-subtle border border-accent/40 text-ink font-medium"
                      : "text-ink-secondary hover:bg-paper hover:text-ink border border-transparent"
                  }`}
                >
                  <div className="truncate pr-5">
                    {session.title || `Investigation #${session.id}`}
                  </div>
                  <button
                    onClick={(e) => handleDeleteSession(session.id, e)}
                    className="opacity-0 group-hover:opacity-100 p-1 text-muted hover:text-ruby transition-opacity"
                    title="Delete investigation"
                  >
                    <svg className="w-3.5 h-3.5" viewBox="0 0 20 20" fill="currentColor">
                      <path fillRule="evenodd" d="M4.293 4.293a1 1 0 011.414 0L10 8.586l4.293-4.293a1 1 0 111.414 1.414L11.414 10l4.293 4.293a1 1 0 01-1.414 1.414L10 11.414l-4.293 4.293a1 1 0 01-1.414-1.414L8.586 10 4.293 5.707a1 1 0 010-1.414z" clipRule="evenodd" />
                    </svg>
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* KNOWLEDGE REPOSITORY SECTION */}
        <div className="flex-1 min-h-[220px] flex flex-col p-3 bg-paper">
          <div className="flex items-center justify-between mb-2">
            <div className="flex gap-2">
              <button
                onClick={() => setActiveDocTab("personal")}
                className={`font-mono text-[11px] uppercase tracking-wider pb-1 transition-colors cursor-pointer border-b-2 ${
                  activeDocTab === "personal"
                    ? "border-accent text-ink font-semibold"
                    : "border-transparent text-muted hover:text-ink"
                }`}
              >
                Personal ({documents.length})
              </button>
              <button
                onClick={() => setActiveDocTab("global")}
                className={`font-mono text-[11px] uppercase tracking-wider pb-1 transition-colors cursor-pointer border-b-2 ${
                  activeDocTab === "global"
                    ? "border-accent text-ink font-semibold"
                    : "border-transparent text-muted hover:text-ink"
                }`}
              >
                Company Corpus ({globalDocuments.length})
              </button>
            </div>
            <button
              onClick={() => {
                fetchDocuments();
                fetchSessions();
              }}
              className="text-muted hover:text-ink p-1 font-mono text-[11px] transition-colors"
              title="Refresh repository"
            >
              ↻
            </button>
          </div>

          <div className="flex-1 overflow-y-auto custom-scrollbar space-y-1.5 my-1">
            {activeDocTab === "personal" ? (
              documents.length === 0 ? (
                <div className="text-center py-6 border border-dashed border-rule rounded-base text-muted text-xs font-mono">
                  [NO_PERSONAL_DOCUMENTS]
                </div>
              ) : (
                documents.map((doc, idx) => (
                  <div
                    key={idx}
                    className="group flex items-center justify-between p-2 rounded-base bg-paper-2 border border-rule hover:border-rule-focus text-xs transition-colors"
                  >
                    <div className="flex items-center gap-1.5 overflow-hidden">
                      <span className="font-mono text-[9px] uppercase px-1 py-0.5 rounded bg-paper border border-rule text-muted">
                        {doc.split('.').pop()}
                      </span>
                      <span className="truncate text-ink-secondary" title={doc}>
                        {doc}
                      </span>
                    </div>
                    <div className="flex items-center gap-1">
                      <button
                        onClick={() => {
                          const prefix = doc.endsWith('.csv') ? '!' : '@';
                          setInput((prev) => `${prev} ${prefix}${doc} `);
                          inputRef.current?.focus();
                        }}
                        className="text-muted hover:text-accent p-0.5 font-mono text-[10px]"
                        title="Target document in prompt"
                      >
                        Target
                      </button>
                      <button
                        onClick={(e) => handleDeleteDoc(doc, e)}
                        className="opacity-0 group-hover:opacity-100 p-0.5 text-muted hover:text-ruby transition-opacity"
                        title="Remove document"
                      >
                        ×
                      </button>
                    </div>
                  </div>
                ))
              )
            ) : (
              globalDocuments.length === 0 ? (
                <div className="text-center py-6 border border-dashed border-rule rounded-base text-muted text-xs font-mono">
                  [NO_GLOBAL_DOCUMENTS]
                </div>
              ) : (
                globalDocuments.map((doc, idx) => (
                  <div
                    key={idx}
                    className="flex items-center justify-between p-2 rounded-base bg-paper-2 border border-rule text-xs"
                  >
                    <div className="flex items-center gap-1.5 overflow-hidden">
                      <span className="font-mono text-[9px] uppercase px-1 py-0.5 rounded bg-paper border border-rule text-muted">
                        {doc.split('.').pop()}
                      </span>
                      <span className="truncate text-ink-secondary" title={doc}>
                        {doc}
                      </span>
                    </div>
                    <button
                      onClick={() => {
                        const prefix = doc.endsWith('.csv') ? '!' : '@';
                        setInput((prev) => `${prev} ${prefix}${doc} `);
                        inputRef.current?.focus();
                      }}
                      className="text-muted hover:text-accent font-mono text-[10px]"
                      title="Target document in prompt"
                    >
                      Target
                    </button>
                  </div>
                ))
              )
            )}
          </div>

          {/* Upload trigger */}
          <div className="pt-2 border-t border-rule mt-auto">
            <input
              type="file"
              ref={fileInputRef}
              onChange={handleUpload}
              className="hidden"
              accept=".txt,.pdf,.csv,.docx"
            />
            <input
              type="file"
              ref={globalFileInputRef}
              onChange={handleGlobalUpload}
              className="hidden"
              accept=".txt,.pdf,.csv,.docx"
            />
            {activeDocTab === "personal" ? (
              <button
                onClick={() => fileInputRef.current?.click()}
                disabled={isUploading}
                className="w-full py-2 px-3 rounded-base bg-paper-2 hover:bg-paper-3 border border-rule hover:border-accent text-ink text-xs font-mono uppercase tracking-wider font-medium transition-colors disabled:opacity-50 cursor-pointer flex items-center justify-center gap-2"
              >
                {isUploading ? "Processing Task..." : "+ Ingest Document"}
              </button>
            ) : (
              (["superadmin", "admin", "editor"].includes(userRole) || isPlatformAdmin) ? (
                <button
                  onClick={() => globalFileInputRef.current?.click()}
                  disabled={isUploading}
                  className="w-full py-2 px-3 rounded-base bg-paper-2 hover:bg-paper-3 border border-rule hover:border-accent text-ink text-xs font-mono uppercase tracking-wider font-medium transition-colors disabled:opacity-50 cursor-pointer flex items-center justify-center gap-2"
                >
                  {isUploading ? "Uploading Global..." : "+ Ingest Company Doc"}
                </button>
              ) : (
                <div className="text-center font-mono text-[10px] text-muted py-1">
                  [GLOBAL_UPLOAD: EDITOR_ROLE_REQUIRED]
                </div>
              )
            )}
          </div>
        </div>
      </aside>

      {/* MAIN INVESTIGATION CONSOLE */}
      <main className="flex-1 flex flex-col bg-paper relative overflow-hidden">
        
        {/* TOP STATUS BAR */}
        <header className="h-12 border-b border-rule px-6 flex items-center justify-between bg-paper-2 shrink-0 z-10">
          <div className="flex items-center gap-3">
            <span className="font-mono text-xs uppercase text-muted font-medium">Session:</span>
            <span className="font-display font-medium text-sm text-ink truncate max-w-md">
              {activeSessionTitle}
            </span>
          </div>

          <div className="flex items-center gap-4 text-xs font-mono text-muted">
            <div className="hidden md:flex items-center gap-2">
              <span className="w-1.5 h-1.5 rounded-full bg-emerald" />
              <span>ChromaDB Ready · 384d</span>
            </div>
            <div className="hidden sm:flex items-center gap-2 border-l border-rule pl-4">
              <span className="w-1.5 h-1.5 rounded-full bg-accent" />
              <span>Groq / GPT-OSS-120B</span>
            </div>
          </div>
        </header>

        {/* INCOMING OWNERSHIP TRANSFER HANDSHAKE BANNER */}
        {incomingTransfer && (
          <div className="bg-amber-500/15 border-b border-amber-500/30 px-6 py-2.5 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-2 text-xs font-mono shrink-0">
            <div className="flex items-center gap-2 text-amber-500 font-semibold">
              <span className="w-2 h-2 rounded-full bg-amber-500 animate-pulse" />
              <span>👑 SuperAdmin Ownership Transfer Offer from &apos;{incomingTransfer.from_username}&apos;</span>
            </div>
            <div className="flex items-center gap-2">
              <button
                onClick={() => handleAcceptIncomingTransfer(incomingTransfer.id)}
                className="px-3 py-1 bg-emerald text-black font-semibold rounded text-[11px] uppercase tracking-wider hover:opacity-90 cursor-pointer"
              >
                Accept Ownership →
              </button>
              <button
                onClick={() => handleRejectIncomingTransfer(incomingTransfer.id)}
                className="px-2 py-1 bg-paper text-muted hover:text-ruby text-[11px] uppercase tracking-wider rounded border border-rule cursor-pointer"
              >
                Decline
              </button>
            </div>
          </div>
        )}

        {/* MESSAGE STREAM AREA */}
        <div className="flex-1 overflow-y-auto px-4 md:px-8 py-6 space-y-6 custom-scrollbar">
          
          {/* Workstation Readiness Dossier (When no messages exist yet) */}
          {messages.length === 0 && (
            <div className="max-w-3xl mx-auto my-6 p-6 bg-paper-2 rounded-card border border-rule shadow-sm">
              <div className="flex items-center gap-2 mb-2 pb-2 border-b border-rule">
                <span className="w-2 h-2 rounded-full bg-accent" />
                <span className="font-mono text-xs uppercase tracking-wider text-muted font-medium">
                  Workspace Dossier Ready
                </span>
              </div>
              <h2 className="text-lg font-display font-semibold text-ink mb-1">
                Enterprise Knowledge & Tabular Engine
              </h2>
              <p className="text-xs text-muted mb-6">
                Direct vector queries via hybrid ChromaDB + BM25 fusion or SQL analytical execution across CSV tables.
              </p>

              <div className="space-y-2">
                <span className="font-mono text-[11px] uppercase tracking-wider text-muted block mb-1">
                  Preset Inquiries:
                </span>
                <button
                  onClick={() => handleSend("Which department has the highest YTD expenses in !Employee_ID,Employee_Name,Departmen.csv?")}
                  className="w-full text-left p-3 rounded-base bg-paper hover:bg-paper-3 border border-rule hover:border-accent text-xs font-body text-ink transition-all flex items-center justify-between group cursor-pointer"
                >
                  <div className="flex items-center gap-2 overflow-hidden">
                    <span className="font-mono text-[10px] px-1.5 py-0.5 rounded bg-emerald-subtle text-emerald border border-emerald/30 uppercase font-semibold shrink-0">
                      SQL
                    </span>
                    <span className="truncate">Which department has the highest YTD expenses in <strong>!Employee_ID,Employee_Name,Departmen.csv</strong>?</span>
                  </div>
                  <span className="font-mono text-[11px] text-muted group-hover:text-accent shrink-0 ml-3">Execute SQL →</span>
                </button>
                <button
                  onClick={() => handleSend("What is the total Q1 revenue generated by the Enterprise Sales department?")}
                  className="w-full text-left p-3 rounded-base bg-paper hover:bg-paper-3 border border-rule hover:border-accent text-xs font-body text-ink transition-all flex items-center justify-between group cursor-pointer"
                >
                  <div className="flex items-center gap-2 overflow-hidden">
                    <span className="font-mono text-[10px] px-1.5 py-0.5 rounded bg-emerald-subtle text-emerald border border-emerald/30 uppercase font-semibold shrink-0">
                      CALC
                    </span>
                    <span className="truncate">What is the total Q1 revenue generated by the Enterprise Sales department?</span>
                  </div>
                  <span className="font-mono text-[11px] text-muted group-hover:text-accent shrink-0 ml-3">Calculate →</span>
                </button>
                <button
                  onClick={() => handleSend("Summarize the policy guidelines and procedures mentioned in the uploaded documents.")}
                  className="w-full text-left p-3 rounded-base bg-paper hover:bg-paper-3 border border-rule hover:border-accent text-xs font-body text-ink transition-all flex items-center justify-between group cursor-pointer"
                >
                  <div className="flex items-center gap-2 overflow-hidden">
                    <span className="font-mono text-[10px] px-1.5 py-0.5 rounded bg-accent-subtle text-accent border border-accent/30 uppercase font-semibold shrink-0">
                      RRF
                    </span>
                    <span className="truncate">Summarize the policy guidelines and procedures mentioned in uploaded documents.</span>
                  </div>
                  <span className="font-mono text-[11px] text-muted group-hover:text-accent shrink-0 ml-3">RRF Retrieve →</span>
                </button>
              </div>

              <div className="mt-6 pt-4 border-t border-rule flex items-center justify-between text-[11px] font-mono text-muted">
                <span>Target files: Type <code className="text-ink bg-paper px-1 rounded border border-rule">@file</code> or <code className="text-ink bg-paper px-1 rounded border border-rule">!table</code></span>
                <span>Hybrid RRF Reranker Active</span>
              </div>
            </div>
          )}

          {/* Actual Messages */}
          {messages.map((msg, i) => (
            <div
              key={i}
              className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}
            >
              <div
                className={`w-full max-w-4xl rounded-card p-4 sm:p-5 overflow-hidden ${
                  msg.role === "user"
                    ? "bg-paper-3 text-ink border border-rule-focus"
                    : "bg-paper-2 text-ink-secondary border border-rule shadow-sm"
                }`}
              >
                {/* Assistant Telemetry Header */}
                {msg.role === "assistant" && (
                  <div className="flex items-center justify-between pb-3 mb-3 border-b border-rule text-[11px] font-mono text-muted">
                    <div className="flex items-center gap-2">
                      <span className="w-1.5 h-1.5 rounded-full bg-accent" />
                      <span className="uppercase tracking-wider">Inference Telemetry</span>
                    </div>
                    <span>GPT-OSS-120B // RRF-Rerank</span>
                  </div>
                )}

                {/* Content Render */}
                <div className={msg.role === "assistant" ? "markdown-body overflow-x-auto custom-scrollbar" : "text-sm text-ink font-body leading-relaxed whitespace-pre-wrap break-words"}>
                  {msg.role === "assistant" ? (
                    <ReactMarkdown 
                      remarkPlugins={[remarkGfm]}
                      components={{
                        table({children, ...props}: any) {
                          return (
                            <div className="w-full my-3 overflow-x-auto rounded-base border border-rule bg-paper custom-scrollbar">
                              <table {...props} className="w-full text-xs text-left border-collapse whitespace-nowrap min-w-full">
                                {children}
                              </table>
                            </div>
                          );
                        },
                        thead({children, ...props}: any) {
                          return (
                            <thead {...props} className="bg-paper-3 border-b border-rule font-mono text-[11px] uppercase tracking-wider text-muted font-semibold">
                              {children}
                            </thead>
                          );
                        },
                        tbody({children, ...props}: any) {
                          return (
                            <tbody {...props} className="divide-y divide-rule font-body">
                              {children}
                            </tbody>
                          );
                        },
                        tr({children, ...props}: any) {
                          return (
                            <tr {...props} className="hover:bg-paper-2/60 transition-colors">
                              {children}
                            </tr>
                          );
                        },
                        th({children, ...props}: any) {
                          return (
                            <th {...props} className="px-3.5 py-2 font-semibold text-ink border-r border-rule last:border-r-0">
                              {children}
                            </th>
                          );
                        },
                        td({children, ...props}: any) {
                          return (
                            <td {...props} className="px-3.5 py-2 text-ink-secondary border-r border-rule last:border-r-0 font-mono text-xs">
                              {children}
                            </td>
                          );
                        },
                        code({node, inline, className, children, ...props}: any) {
                          const match = /language-(\w+)/.exec(className || '');
                          if (!inline && match) {
                            return (
                              <div className="my-3 rounded-base overflow-hidden border border-rule">
                                <div className="px-3 py-1 bg-paper-3 border-b border-rule text-[10px] font-mono uppercase text-muted flex justify-between items-center">
                                  <span>{match[1]}</span>
                                  <span>Engine Output</span>
                                </div>
                                <SyntaxHighlighter
                                  {...props}
                                  style={vscDarkPlus}
                                  language={match[1]}
                                  PreTag="div"
                                  customStyle={{ margin: 0, background: 'var(--color-paper)' }}
                                >
                                  {String(children).replace(/\n$/, '')}
                                </SyntaxHighlighter>
                              </div>
                            );
                          }
                          const text = String(children);
                          if (text.startsWith('📄')) {
                            return (
                              <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded border border-brass/40 bg-brass-subtle text-brass font-mono text-[11px] font-medium align-middle mx-1 shadow-xs">
                                {children}
                              </span>
                            );
                          }
                          return (
                            <code {...props} className="font-mono text-xs px-1.5 py-0.5 rounded bg-paper-3 border border-rule text-ink">
                              {children}
                            </code>
                          );
                        }
                      }}
                    >
                      {msg.content.replace(
                        /[\[\u3010\(]Source:\s*([^,\]\u3011\)]+)(?:,\s*(?:Page\s*)?([^\]\u3011\)]+))?[\]\u3011\)]/gi,
                        (_, file, page) => (page ? `\`📄 ${file.trim()} · Page ${page.trim()}\`` : `\`📄 ${file.trim()}\``)
                      )}
                    </ReactMarkdown>
                  ) : (
                    msg.content
                  )}
                </div>
              </div>
            </div>
          ))}

          {/* Tactile Processing Telemetry readout (Zero bouncing dots) */}
          {isTyping && (
            <div className="flex justify-start">
              <div className="bg-paper-2 border border-rule rounded-card px-4 py-3 flex items-center gap-3">
                <span className="w-2 h-2 rounded-full bg-accent animate-ping" />
                <span className="font-mono text-xs text-muted">
                  [PROCESSING] Executing hybrid retrieval & inference pipeline...
                </span>
              </div>
            </div>
          )}

          <div ref={messagesEndRef} />
        </div>

        {/* BOTTOM COMMAND CONSOLE / INPUT AREA */}
        <div className="p-4 md:px-8 md:py-4 bg-paper border-t border-rule shrink-0 z-20">
          <div className="max-w-4xl mx-auto relative">
            
            {/* AUTOCOMPLETE FLOATING MENU (@ and !) */}
            {showMentionMenu && filteredDocs.length > 0 && (
              <div className="absolute bottom-full left-0 mb-2 w-full max-w-md bg-paper-2 border border-rule rounded-card shadow-lg overflow-hidden z-50">
                <div className="px-3 py-2 bg-paper-3 border-b border-rule flex justify-between items-center text-[11px] font-mono text-muted uppercase">
                  <span>Target {mentionPrefix === '!' ? 'Tabular Dataset' : 'Document'}</span>
                  <span>Use ↑↓ and Return</span>
                </div>
                <ul className="max-h-56 overflow-y-auto custom-scrollbar p-1">
                  {filteredDocs.map((doc, idx) => (
                    <li key={idx}>
                      <button
                        onClick={() => handleSelectMention(doc)}
                        className={`w-full text-left px-3 py-2 rounded-base text-xs font-mono transition-colors flex items-center justify-between cursor-pointer ${
                          mentionIndex === idx 
                            ? "bg-accent text-accent-ink" 
                            : "text-ink hover:bg-paper-3"
                        }`}
                      >
                        <span className="truncate">{doc}</span>
                        <span className="text-[10px] opacity-70 uppercase">
                          {doc.split('.').pop()}
                        </span>
                      </button>
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {/* Input Bar */}
            <div className="relative flex items-center bg-paper-2 border border-rule focus-within:border-accent rounded-card overflow-hidden transition-colors">
              <input
                ref={inputRef}
                type="text"
                value={input}
                onChange={handleInputChange}
                onKeyDown={(e) => {
                  if (showMentionMenu && filteredDocs.length > 0) {
                    if (e.key === "ArrowDown") {
                      e.preventDefault();
                      setMentionIndex((prev) => Math.min(prev + 1, filteredDocs.length - 1));
                      return;
                    }
                    if (e.key === "ArrowUp") {
                      e.preventDefault();
                      setMentionIndex((prev) => Math.max(prev - 1, 0));
                      return;
                    }
                    if (e.key === "Enter") {
                      e.preventDefault();
                      handleSelectMention(filteredDocs[mentionIndex]);
                      return;
                    }
                    if (e.key === "Escape") {
                      setShowMentionMenu(false);
                      return;
                    }
                  }
                  if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault();
                    handleSend();
                  }
                }}
                disabled={isTyping}
                placeholder={
                  isTyping 
                    ? "Inference pipeline streaming response..." 
                    : "Ask anything or query data (use @ for documents, ! for tables)..."
                }
                className="flex-1 bg-transparent border-none py-3 px-4 text-ink placeholder:text-muted focus:outline-none text-xs sm:text-sm font-body disabled:opacity-50"
              />
              <button
                onClick={() => handleSend()}
                disabled={!input.trim() || isTyping}
                className="px-4 py-2 mr-2 rounded-base bg-accent hover:bg-accent-hover active:scale-[0.99] text-accent-ink text-xs font-mono uppercase tracking-wider font-semibold disabled:bg-paper-3 disabled:border-rule disabled:text-muted transition-all cursor-pointer disabled:cursor-not-allowed focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-focus"
              >
                ↵ Submit
              </button>
            </div>

            <div className="mt-2 flex items-center justify-between text-[11px] font-mono text-muted px-1">
              <div className="flex gap-3">
                <span>[Return] Send query</span>
                <span>[@] Target doc</span>
                <span>[!] SQL table</span>
              </div>
              <span className="hidden sm:inline">Engine: Groq OSS-120B</span>
            </div>
          </div>
        </div>
      </main>

      {/* PRIVILEGE ESCALATION MODAL */}
      {isRequestingRole && (
        <div className="fixed inset-0 bg-paper/80 backdrop-blur-xs z-50 flex items-center justify-center p-4">
          <div className="bg-paper-2 border border-rule p-6 rounded-card max-w-md w-full shadow-lg">
            <div className="flex items-center gap-2 mb-2 pb-2 border-b border-rule">
              <span className="w-2 h-2 rounded-full bg-accent" />
              <span className="font-mono text-xs uppercase tracking-wider text-muted font-medium">
                Authorization Gateway
              </span>
            </div>
            <h2 className="text-lg font-display font-semibold text-ink mb-1">
              Request Privilege Escalation
            </h2>
            <p className="text-xs text-muted mb-5">
              Select access tier for administrative or global editorial rights.
            </p>
            
            <div className="space-y-3">
              <button
                onClick={() => handleRoleRequest("editor")}
                className="w-full text-left p-4 rounded-base border border-rule bg-paper hover:border-accent transition-colors group cursor-pointer"
              >
                <div className="font-semibold text-sm text-ink">EDITOR</div>
                <div className="text-xs text-muted mt-0.5">Ingest and curate global documents across all enterprise sessions.</div>
              </button>
              
              <button
                onClick={() => handleRoleRequest("admin")}
                className="w-full text-left p-4 rounded-base border border-rule bg-paper hover:border-accent transition-colors group cursor-pointer"
              >
                <div className="font-semibold text-sm text-ink">ADMINISTRATOR</div>
                <div className="text-xs text-muted mt-0.5">Full console telemetry, user role assignment, and corpus administration.</div>
              </button>
            </div>
            
            <div className="mt-6 flex justify-end">
              <button
                onClick={() => setIsRequestingRole(false)}
                className="px-4 py-2 text-xs font-mono uppercase tracking-wider text-muted hover:text-ink border border-rule hover:border-rule-focus rounded-base transition-colors cursor-pointer"
              >
                Cancel
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

