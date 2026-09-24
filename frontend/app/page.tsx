"use client";

import { useState, useRef, useEffect } from "react";
import { useRouter } from "next/navigation";
import ReactMarkdown, { Components } from 'react-markdown';
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
  const [messages, setMessages] = useState<Message[]>([
    { role: "assistant", content: "Hello! Start a new chat, upload documents, and ask me anything about them." },
  ]);
  const [input, setInput] = useState("");
  const [documents, setDocuments] = useState<string[]>([]);
  const [globalDocuments, setGlobalDocuments] = useState<string[]>([]);
  const [sessions, setSessions] = useState<Session[]>([]);
  const [activeSessionId, setActiveSessionId] = useState<number | null>(null);
  const [userRole, setUserRole] = useState<string>("user");
  const [pendingRequest, setPendingRequest] = useState<string | null>(null);
  const [isRequestingRole, setIsRequestingRole] = useState(false);
  const [isGlobalDocsOpen, setIsGlobalDocsOpen] = useState(false);
  
  const [isUploading, setIsUploading] = useState(false);
  const [isTyping, setIsTyping] = useState(false);
  
  // Mention menu states
  const [showMentionMenu, setShowMentionMenu] = useState(false);
  const [mentionQuery, setMentionQuery] = useState("");
  const [mentionIndex, setMentionIndex] = useState(0);
  
  const fileInputRef = useRef<HTMLInputElement>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const router = useRouter();

  // Helper for authenticated fetch
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
    } catch (err: any) {
      if (err.name === 'TypeError' && err.message.includes('Failed to fetch')) {
        toast.error("Cannot connect to the backend server. Please check your network configuration.");
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
        setUserRole(data.role || "user");
      }
      
      const reqRes = await authFetch(`${API_URL}/auth/my_request`);
      if (reqRes.ok) {
        const reqData = await reqRes.json();
        if (reqData) {
            setPendingRequest(reqData.status === "pending" ? reqData.requested_role : null);
        }
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
        // Automatically select the most recent session if none is selected
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
        if (data.length > 0) {
            setMessages(data);
        } else {
            setMessages([{ role: "assistant", content: "New chat started. What would you like to know?" }]);
        }
      }
    } catch (error) {
      console.error("Failed to fetch messages:", error);
    }
  };

  const handleNewChat = async () => {
    try {
      const res = await authFetch(`${API_URL}/sessions`, {
          method: "POST"
      });
      if (res.ok) {
          const newSession = await res.json();
          await fetchSessions();
          setActiveSessionId(newSession.id);
      }
    } catch (error) {
       console.error("Failed to create new chat:", error);
    }
  };

  const handleDeleteSession = async (sessionId: number) => {
    try {
      const res = await authFetch(`${API_URL}/sessions/${sessionId}`, {
        method: "DELETE",
      });
      if (res.ok) {
        toast.success("Chat deleted");
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
        toast.success("Document uploaded successfully");
        await fetchDocuments();
      } else {
        const err = await res.json();
        toast.error(`Upload failed: ${err.detail}`);
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
        toast.success("Global document uploaded successfully");
        await fetchDocuments();
      } else {
        const err = await res.json();
        toast.error(`Global Upload failed: ${err.detail}`);
      }
    } catch (error) {
      console.error("Upload error:", error);
      toast.error("Failed to connect to backend for global upload.");
    } finally {
      setIsUploading(false);
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
        toast.success(`Requested ${role} access successfully!`);
      } else {
        const err = await res.json();
        toast.error(`Request failed: ${err.detail}`);
      }
    } catch (error) {
        console.error("Role request error:", error);
    }
  };

  const handleDelete = async (filename: string) => {
    try {
      const res = await authFetch(`${API_URL}/documents/${encodeURIComponent(filename)}`, {
        method: "DELETE",
      });
      if (res.ok) {
        toast.success("Document deleted");
        await fetchDocuments();
      } else {
        const err = await res.json();
        toast.error(`Delete failed: ${err.detail || "Unknown error"}`);
      }
    } catch (error) {
      console.error("Delete error:", error);
      toast.error("Failed to connect to backend for deletion.");
    }
  };

  // Auto-scroll to bottom of chat
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

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
    } else {
      setMessages([
        { role: "assistant", content: "Hello! Start a new chat, upload documents, and ask me anything about them." },
      ]);
    }
  }, [activeSessionId]); // eslint-disable-line react-hooks/exhaustive-deps

  const handleInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const val = e.target.value;
    setInput(val);

    const match = val.match(/!([\w\.,_-]*)$/);
    if (match) {
      setShowMentionMenu(true);
      setMentionQuery(match[1]);
      setMentionIndex(0);
    } else {
      setShowMentionMenu(false);
    }
  };

  const handleSelectMention = (doc: string) => {
    const match = input.match(/!([\w\.,_-]*)$/);
    if (match) {
      const newInput = input.substring(0, match.index) + "!" + doc + " ";
      setInput(newInput);
      setShowMentionMenu(false);
    }
  };

  const filteredDocs = [...documents, ...globalDocuments].filter(d => 
    d.toLowerCase().includes(mentionQuery.toLowerCase())
  );

  const handleSend = async () => {
    if (!input.trim()) return;
    
    // Ensure we have an active session
    const currentSessionId = activeSessionId;
    if (currentSessionId === null) {
       await handleNewChat();
       // Fetch sessions should update state, but to be safe and avoid race conditions we'd ideally await the return ID
       // For now, if activeSessionId is null, handleNewChat sets it shortly.
       return; 
    }

    const userQuery = input.trim();
    setInput("");
    
    const isFirstMessage = messages.length <= 1;
    
    setMessages((prev) => [...prev, { role: "user", content: userQuery }]);
    setIsTyping(true);

    // Placeholder for assistant response
    setMessages((prev) => [...prev, { role: "assistant", content: "" }]);

    if (isFirstMessage) {
        let generatedTitle = userQuery.split(" ").slice(0, 4).join(" ");
        if (generatedTitle.length > 35) {
            generatedTitle = generatedTitle.substring(0, 32);
        }
        generatedTitle += (userQuery.length > generatedTitle.length ? "..." : "");
        handleUpdateSessionTitle(currentSessionId, generatedTitle);
    }

    try {
      const res = await authFetch(`${API_URL}/query`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query: userQuery, session_id: currentSessionId }),
      });

      if (!res.ok) {
        throw new Error("Failed to get response");
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
          content: "Sorry, I encountered an error connecting to the server.",
        };
        return newMessages;
      });
    } finally {
      setIsTyping(false);
    }
  };

  return (
    <div className="flex h-screen bg-paper text-ink font-sans selection:bg-accent selection:text-accent-ink">
      
      {/* SIDEBAR */}
      <div className="w-80 bg-paper-2 border-r border-border flex flex-col z-10">
        <div className="p-m border-b border-border bg-paper-2 flex justify-between items-center">
          <div>
            <h1 className="text-xl font-bold text-ink tracking-tight flex items-center gap-2">
              Enterprise RAG
            </h1>
            <p className="text-sm text-muted mt-1">Knowledge base</p>
          </div>
          <div className="flex flex-col gap-2">
            {userRole === "admin" && (
              <button
                onClick={() => router.push("/admin")}
                className="text-xs bg-paper border border-border hover:border-accent text-ink px-2 py-1 rounded-base transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-focus"
              >
                Admin
              </button>
            )}
            {userRole === "user" && !pendingRequest && (
               <button
                onClick={() => setIsRequestingRole(true)}
                className="text-xs bg-paper border border-border hover:border-accent text-ink px-2 py-1 rounded-base transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-focus"
               >
                 Request Access
               </button>
            )}
            {pendingRequest && (
               <button disabled className="text-xs bg-paper-3 text-muted border border-border px-2 py-1 rounded-base cursor-not-allowed">
                 {pendingRequest} Pending
               </button>
            )}
            <button
              onClick={() => {
                localStorage.removeItem("token");
                router.push("/login");
              }}
              className="text-xs bg-paper border border-border hover:border-accent text-ink px-2 py-1 rounded-base transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-focus"
            >
              Logout
            </button>
          </div>
        </div>

        {/* CHAT HISTORY SECTION */}
        <div className="p-m border-b border-border flex-1 overflow-y-auto custom-scrollbar">
           <div className="flex justify-between items-center mb-4">
               <h2 className="text-xs font-semibold text-muted uppercase tracking-wider">
                 History
               </h2>
               <button 
                  onClick={handleNewChat} 
                  className="text-xs bg-paper border border-border hover:border-accent text-ink px-2 py-1 rounded-base transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-focus"
               >
                   + New
               </button>
           </div>
           
           <ul className="space-y-1">
              {sessions.map((session) => (
                <li key={session.id} className="group relative">
                    <button 
                        onClick={() => setActiveSessionId(session.id)}
                        className={`w-full text-left p-2 rounded-base text-sm truncate transition-colors pr-8 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-focus ${
                            activeSessionId === session.id 
                                ? "bg-accent text-accent-ink" 
                                : "text-ink hover:bg-paper border border-transparent hover:border-border"
                        }`}
                    >
                        {session.title || `Chat #${session.id}`}
                    </button>
                    <button
                      onClick={() => handleDeleteSession(session.id)}
                      className={`absolute right-2 top-1/2 -translate-y-1/2 p-1 rounded-base transition-opacity focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-focus ${
                          activeSessionId === session.id ? "text-accent-ink hover:text-paper" : "text-muted hover:text-ink opacity-0 group-hover:opacity-100"
                      }`}
                      title="Delete Chat"
                    >
                      <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" className="w-4 h-4">
                        <path fillRule="evenodd" d="M8.75 1A2.75 2.75 0 006 3.75v.443c-.795.077-1.584.176-2.365.298a.75.75 0 10.23 1.482l.149-.022.841 10.518A2.75 2.75 0 007.596 19h4.807a2.75 2.75 0 002.742-2.53l.841-10.52.149.023a.75.75 0 00.23-1.482A41.03 41.03 0 0014 4.193V3.75A2.75 2.75 0 0011.25 1h-2.5zM10 4c.84 0 1.673.025 2.5.075V3.75c0-.69-.56-1.25-1.25-1.25h-2.5c-.69 0-1.25.56-1.25 1.25v.325C8.327 4.025 9.16 4 10 4zM8.58 7.72a.75.75 0 00-1.5.06l.3 7.5a.75.75 0 101.5-.06l-.3-7.5zm4.34.06a.75.75 0 10-1.5-.06l-.3 7.5a.75.75 0 101.5.06l.3-7.5z" clipRule="evenodd" />
                      </svg>
                    </button>
                </li>
              ))}
           </ul>
        </div>

        {/* DOCUMENTS SECTION */}
        <div className="flex-1 overflow-y-auto p-m space-y-4 custom-scrollbar">
          <h2 className="text-xs font-semibold text-muted uppercase tracking-wider mb-2">
            Documents
          </h2>
          
          {documents.length === 0 ? (
            <div className="text-sm text-muted text-center py-8 border border-border rounded-base bg-paper">
              No documents yet.
            </div>
          ) : (
            <ul className="space-y-2">
              {documents.map((doc, idx) => (
                <li key={idx} className="group flex items-center justify-between p-3 rounded-base bg-paper border border-border hover:border-accent transition-colors">
                  <span className="text-sm truncate mr-2 text-ink" title={doc}>
                    {doc}
                  </span>
                  <button
                    onClick={() => handleDelete(doc)}
                    className="text-muted hover:text-ink opacity-0 group-hover:opacity-100 transition-opacity p-1 rounded-base focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-focus"
                    title="Remove document"
                  >
                    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" className="w-4 h-4">
                      <path fillRule="evenodd" d="M8.75 1A2.75 2.75 0 006 3.75v.443c-.795.077-1.584.176-2.365.298a.75.75 0 10.23 1.482l.149-.022.841 10.518A2.75 2.75 0 007.596 19h4.807a2.75 2.75 0 002.742-2.53l.841-10.52.149.023a.75.75 0 00.23-1.482A41.03 41.03 0 0014 4.193V3.75A2.75 2.75 0 0011.25 1h-2.5zM10 4c.84 0 1.673.025 2.5.075V3.75c0-.69-.56-1.25-1.25-1.25h-2.5c-.69 0-1.25.56-1.25 1.25v.325C8.327 4.025 9.16 4 10 4zM8.58 7.72a.75.75 0 00-1.5.06l.3 7.5a.75.75 0 101.5-.06l-.3-7.5zm4.34.06a.75.75 0 10-1.5-.06l-.3 7.5a.75.75 0 101.5.06l.3-7.5z" clipRule="evenodd" />
                    </svg>
                  </button>
                </li>
              ))}
            </ul>
          )}
          
          {/* GLOBAL DOCUMENTS */}
          <div className="mt-6">
            <button
              onClick={() => setIsGlobalDocsOpen(!isGlobalDocsOpen)}
              className="w-full flex justify-between items-center text-xs font-semibold text-muted uppercase tracking-wider mb-2 hover:text-ink transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-focus"
            >
              <span>Global Documents ({globalDocuments.length})</span>
              <span>{isGlobalDocsOpen ? "▼" : "▶"}</span>
            </button>
            
            {isGlobalDocsOpen && (
              globalDocuments.length === 0 ? (
                <div className="text-sm text-muted text-center py-4 border border-border rounded-base bg-paper">
                  No global documents.
                </div>
              ) : (
                <ul className="space-y-2 mt-2">
                  {globalDocuments.map((doc, idx) => (
                    <li key={idx} className="flex items-center p-3 rounded-base bg-paper border border-border text-ink">
                      <span className="text-sm truncate" title={doc}>
                        {doc}
                      </span>
                    </li>
                  ))}
                </ul>
              )
            )}
            {isGlobalDocsOpen && (userRole === "admin" || userRole === "editor") && (
              <div className="mt-2">
                <input
                  type="file"
                  id="globalUpload"
                  onChange={handleGlobalUpload}
                  className="hidden"
                  accept=".txt,.pdf,.csv,.docx"
                />
                <button
                  onClick={() => document.getElementById("globalUpload")?.click()}
                  disabled={isUploading}
                  className="w-full text-xs py-2 px-3 border border-border text-ink bg-paper hover:border-accent rounded-base transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-focus"
                >
                  Upload Global Doc
                </button>
              </div>
            )}
          </div>
        </div>

        <div className="p-m border-t border-border bg-paper-2">
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
            className="w-full flex items-center justify-center gap-2 py-2 px-4 rounded-base bg-paper border border-border hover:border-accent text-ink disabled:opacity-50 disabled:cursor-not-allowed text-sm font-medium transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-focus"
          >
            {isUploading ? "Uploading..." : "Upload Document"}
          </button>
        </div>
      </div>

      {/* CHAT AREA */}
      <div className="flex-1 flex flex-col bg-paper relative overflow-hidden">
        
        {/* Atmospheric Radial Blooms */}
        <div className="absolute top-[-200px] right-[-100px] w-[600px] h-[600px] rounded-full bg-accent opacity-[0.07] blur-[100px] pointer-events-none" />
        <div className="absolute bottom-[100px] left-[-100px] w-[500px] h-[500px] rounded-full bg-accent opacity-[0.05] blur-[80px] pointer-events-none" />

        <div className="flex-1 overflow-y-auto p-l space-y-6 custom-scrollbar z-10 relative">
          {messages.map((msg, i) => (
            <div
              key={i}
              className={`flex ${
                msg.role === "user" ? "justify-end" : "justify-start"
              }`}
            >
              <div
                className={`max-w-3xl rounded-base px-5 py-4 ${
                  msg.role === "user"
                    ? "bg-accent text-accent-ink border border-transparent shadow-[0_4px_24px_rgba(0,0,0,0.1)] shadow-accent/20"
                    : "bg-paper-2 text-ink border border-border"
                }`}
              >
                <div className={`whitespace-pre-wrap leading-relaxed text-sm md:text-base ${msg.role === "assistant" ? "markdown-body" : ""}`}>
                  {msg.role === "assistant" ? (
                    <ReactMarkdown 
                      remarkPlugins={[remarkGfm]}
                      components={{
                        code({node, inline, className, children, ...props}: any) {
                          const match = /language-(\w+)/.exec(className || '')
                          return !inline && match ? (
                            <SyntaxHighlighter
                              {...props}
                              style={vscDarkPlus}
                              language={match[1]}
                              PreTag="div"
                            >
                              {String(children).replace(/\n$/, '')}
                            </SyntaxHighlighter>
                          ) : (
                            <code {...props} className={className}>
                              {children}
                            </code>
                          )
                        }
                      }}
                    >
                      {msg.content}
                    </ReactMarkdown>
                  ) : (
                    msg.content
                  )}
                </div>
              </div>
            </div>
          ))}
          {isTyping && (
            <div className="flex justify-start">
              <div className="bg-paper border border-border text-muted rounded-base px-5 py-4 w-24 flex items-center justify-center gap-1">
                <span className="w-2 h-2 rounded-full bg-border animate-bounce [animation-delay:-0.3s]"></span>
                <span className="w-2 h-2 rounded-full bg-border animate-bounce [animation-delay:-0.15s]"></span>
                <span className="w-2 h-2 rounded-full bg-border animate-bounce"></span>
              </div>
            </div>
          )}
          <div ref={messagesEndRef} />
        </div>

        {/* INPUT AREA */}
        <div className="p-4 md:px-6 md:py-4 bg-paper border-t border-border z-10 relative">
          <div className="max-w-4xl mx-auto relative group">
            
            {/* AUTOCOMPLETE MENU */}
            {showMentionMenu && filteredDocs.length > 0 && (
              <div className="absolute bottom-full left-0 mb-2 w-full max-w-md bg-paper border border-border rounded-base shadow-sm overflow-hidden z-50">
                <div className="px-3 py-2 bg-paper-2 border-b border-border text-xs font-semibold text-muted uppercase">
                  Select a document
                </div>
                <ul className="max-h-60 overflow-y-auto custom-scrollbar">
                  {filteredDocs.map((doc, idx) => (
                    <li key={idx}>
                      <button
                        onClick={() => handleSelectMention(doc)}
                        className={`w-full text-left px-4 py-3 text-sm transition-colors flex items-center gap-2 ${
                          mentionIndex === idx 
                            ? "bg-accent text-accent-ink" 
                            : "text-ink hover:bg-paper-2"
                        }`}
                      >
                        {doc}
                      </button>
                    </li>
                  ))}
                </ul>
              </div>
            )}

            <div className="relative flex items-center bg-paper border border-border hover:border-accent rounded-base overflow-hidden transition-colors">
              <input
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
                  }
                  if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault();
                    handleSend();
                  }
                }}
                disabled={activeSessionId === null}
                placeholder={activeSessionId === null ? "Create a new chat to begin..." : "Ask a question..."}
                className="flex-1 bg-transparent border-none py-4 px-4 text-ink placeholder-muted focus:outline-none focus:ring-0 disabled:opacity-50 text-sm md:text-base"
              />
              <button
                onClick={handleSend}
                disabled={!input.trim() || activeSessionId === null}
                className="px-4 py-2 mr-2 bg-accent text-accent-ink border border-accent rounded-base disabled:bg-paper-3 disabled:border-border disabled:text-muted transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-focus"
              >
                Send
              </button>
            </div>
          </div>
        </div>
      </div>

      {/* ROLE REQUEST MODAL */}
      {isRequestingRole && (
        <div className="fixed inset-0 bg-ink/20 backdrop-blur-sm z-50 flex items-center justify-center p-4">
          <div className="bg-paper border border-border p-l rounded-base max-w-md w-full shadow-sm">
            <h2 className="text-xl font-bold text-ink mb-2 tracking-tight">Request Access</h2>
            <p className="text-sm text-muted mb-6">
              Select the role you need. An administrator will review your request.
            </p>
            
            <div className="space-y-3">
              <button
                onClick={() => handleRoleRequest("editor")}
                className="w-full text-left p-4 rounded-base border border-border bg-paper hover:border-accent transition-colors group focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-focus"
              >
                <div className="font-semibold text-ink">Editor</div>
                <div className="text-xs text-muted mt-1">Upload and manage Global Documents for all users.</div>
              </button>
              
              <button
                onClick={() => handleRoleRequest("admin")}
                className="w-full text-left p-4 rounded-base border border-border bg-paper hover:border-accent transition-colors group focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-focus"
              >
                <div className="font-semibold text-ink">Admin</div>
                <div className="text-xs text-muted mt-1">Full system access, role management, and analytics.</div>
              </button>
            </div>
            
            <div className="mt-6 flex justify-end">
              <button
                onClick={() => setIsRequestingRole(false)}
                className="px-4 py-2 text-sm text-ink border border-transparent hover:border-border rounded-base transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-focus"
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
