"use client";

import { useState, useRef, useEffect } from "react";
import { useRouter } from "next/navigation";
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

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
  const [isAdmin, setIsAdmin] = useState(false);
  const [isGlobalDocsOpen, setIsGlobalDocsOpen] = useState(false);
  
  const [isUploading, setIsUploading] = useState(false);
  const [isTyping, setIsTyping] = useState(false);
  
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
    const res = await fetch(url, { ...options, headers });
    if (res.status === 401) {
      localStorage.removeItem("token");
      router.push("/login");
      throw new Error("Unauthorized");
    }
    return res;
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
        setIsAdmin(data.is_admin);
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
        await fetchDocuments();
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
      const res = await authFetch(`${API_URL}/documents/${filename}`, {
        method: "DELETE",
      });
      if (res.ok) {
        await fetchDocuments();
      }
    } catch (error) {
      console.error("Delete error:", error);
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
    setMessages((prev) => [...prev, { role: "user", content: userQuery }]);
    setIsTyping(true);

    // Placeholder for assistant response
    setMessages((prev) => [...prev, { role: "assistant", content: "" }]);

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
    <div className="flex h-screen bg-slate-900 text-slate-100 font-sans selection:bg-indigo-500/30">
      
      {/* SIDEBAR */}
      <div className="w-80 bg-slate-950 border-r border-slate-800 flex flex-col shadow-2xl z-10">
        <div className="p-6 border-b border-slate-800 bg-slate-900/50 backdrop-blur flex justify-between items-center">
          <div>
            <h1 className="text-xl font-bold bg-gradient-to-r from-indigo-400 to-cyan-400 bg-clip-text text-transparent flex items-center gap-2">
              Enterprise RAG
            </h1>
            <p className="text-sm text-slate-500 mt-1">Multi-format knowledge base</p>
          </div>
          <div className="flex flex-col gap-2">
            {isAdmin && (
              <button
                onClick={() => router.push("/admin")}
                className="text-xs bg-indigo-500/20 hover:bg-indigo-500/30 border border-indigo-500/50 text-indigo-300 px-2 py-1 rounded transition"
              >
                Admin
              </button>
            )}
            <button
              onClick={() => {
                localStorage.removeItem("token");
                router.push("/login");
              }}
              className="text-xs bg-slate-800 hover:bg-slate-700 text-slate-300 px-2 py-1 rounded transition"
            >
              Logout
            </button>
          </div>
        </div>

        {/* CHAT HISTORY SECTION */}
        <div className="p-4 border-b border-slate-800 flex-1 overflow-y-auto custom-scrollbar">
           <div className="flex justify-between items-center mb-4">
               <h2 className="text-xs font-semibold text-slate-500 uppercase tracking-wider">
                 Chat History
               </h2>
               <button onClick={handleNewChat} className="text-xs bg-indigo-600 hover:bg-indigo-500 text-white px-2 py-1 rounded transition">
                   + New
               </button>
           </div>
           
           <ul className="space-y-1">
              {sessions.map((session) => (
                <li key={session.id}>
                    <button 
                        onClick={() => setActiveSessionId(session.id)}
                        className={`w-full text-left p-2 rounded text-sm truncate transition-colors ${
                            activeSessionId === session.id 
                                ? "bg-indigo-500/20 text-indigo-300 border border-indigo-500/30" 
                                : "text-slate-400 hover:bg-slate-800/50 hover:text-slate-200 border border-transparent"
                        }`}
                    >
                        💬 Chat #{session.id} - {new Date(session.created_at).toLocaleDateString()}
                    </button>
                </li>
              ))}
           </ul>
        </div>

        {/* DOCUMENTS SECTION */}
        <div className="flex-1 overflow-y-auto p-4 space-y-4 custom-scrollbar">
          <h2 className="text-xs font-semibold text-slate-500 uppercase tracking-wider mb-2">
            Indexed Documents
          </h2>
          
          {documents.length === 0 ? (
            <div className="text-sm text-slate-600 text-center py-8 border border-dashed border-slate-800 rounded-xl bg-slate-900/20">
              No documents yet.
            </div>
          ) : (
            <ul className="space-y-2">
              {documents.map((doc, idx) => (
                <li key={idx} className="group flex items-center justify-between p-3 rounded-lg bg-slate-900 border border-slate-800 hover:border-indigo-500/50 hover:bg-slate-800/50 transition-all">
                  <span className="text-sm truncate mr-2" title={doc}>
                    📄 {doc}
                  </span>
                  <button
                    onClick={() => handleDelete(doc)}
                    className="text-slate-500 hover:text-red-400 opacity-0 group-hover:opacity-100 transition-opacity"
                    title="Remove document"
                  >
                    ✕
                  </button>
                </li>
              ))}
            </ul>
          )}
          
          {/* GLOBAL DOCUMENTS */}
          <div className="mt-6">
            <button
              onClick={() => setIsGlobalDocsOpen(!isGlobalDocsOpen)}
              className="w-full flex justify-between items-center text-xs font-semibold text-slate-500 uppercase tracking-wider mb-2 hover:text-slate-400 transition"
            >
              <span>Global Documents ({globalDocuments.length})</span>
              <span>{isGlobalDocsOpen ? "▼" : "▶"}</span>
            </button>
            
            {isGlobalDocsOpen && (
              globalDocuments.length === 0 ? (
                <div className="text-sm text-slate-600 text-center py-4 border border-dashed border-slate-800 rounded-xl bg-slate-900/20">
                  No global documents.
                </div>
              ) : (
                <ul className="space-y-2 mt-2">
                  {globalDocuments.map((doc, idx) => (
                    <li key={idx} className="flex items-center p-3 rounded-lg bg-slate-900/50 border border-slate-800 text-slate-400">
                      <span className="text-sm truncate" title={doc}>
                        📄 {doc}
                      </span>
                    </li>
                  ))}
                </ul>
              )
            )}
          </div>
        </div>

        <div className="p-4 border-t border-slate-800 bg-slate-900/50">
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
            className="w-full flex items-center justify-center gap-2 py-3 px-4 rounded-xl bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 disabled:cursor-not-allowed text-sm font-medium transition-colors shadow-lg shadow-indigo-900/20"
          >
            {isUploading ? "Uploading..." : "Upload Document"}
          </button>
        </div>
      </div>

      {/* CHAT AREA */}
      <div className="flex-1 flex flex-col bg-[radial-gradient(ellipse_at_top_right,_var(--tw-gradient-stops))] from-slate-900 via-slate-900 to-slate-950 relative overflow-hidden">
        
        {/* Background ambient light */}
        <div className="absolute top-0 right-0 w-[500px] h-[500px] bg-indigo-500/10 blur-[120px] rounded-full pointer-events-none"></div>

        <div className="flex-1 overflow-y-auto p-6 space-y-6 custom-scrollbar z-10 relative">
          {messages.map((msg, i) => (
            <div
              key={i}
              className={`flex ${
                msg.role === "user" ? "justify-end" : "justify-start"
              }`}
            >
              <div
                className={`max-w-3xl rounded-2xl px-5 py-4 shadow-sm ${
                  msg.role === "user"
                    ? "bg-indigo-600 text-white rounded-br-none"
                    : "bg-slate-800/80 border border-slate-700/50 text-slate-200 rounded-bl-none backdrop-blur-sm"
                }`}
              >
                <div className={`whitespace-pre-wrap leading-relaxed text-sm md:text-base ${msg.role === "assistant" ? "markdown-body" : ""}`}>
                  {msg.role === "assistant" ? (
                    <ReactMarkdown remarkPlugins={[remarkGfm]}>
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
              <div className="bg-slate-800/80 border border-slate-700/50 text-slate-400 rounded-2xl rounded-bl-none px-5 py-4 w-24 flex items-center justify-center gap-1 backdrop-blur-sm">
                <span className="w-2 h-2 rounded-full bg-slate-500 animate-bounce [animation-delay:-0.3s]"></span>
                <span className="w-2 h-2 rounded-full bg-slate-500 animate-bounce [animation-delay:-0.15s]"></span>
                <span className="w-2 h-2 rounded-full bg-slate-500 animate-bounce"></span>
              </div>
            </div>
          )}
          <div ref={messagesEndRef} />
        </div>

        {/* INPUT AREA */}
        <div className="p-6 bg-transparent z-10 relative">
          <div className="max-w-4xl mx-auto relative group">
            <div className="absolute -inset-1 bg-gradient-to-r from-indigo-500 to-cyan-500 rounded-2xl blur opacity-25 group-hover:opacity-40 transition duration-1000 group-hover:duration-200"></div>
            <div className="relative flex items-center bg-slate-800 border border-slate-700 rounded-2xl overflow-hidden shadow-2xl">
              <input
                type="text"
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault();
                    handleSend();
                  }
                }}
                disabled={activeSessionId === null}
                placeholder={activeSessionId === null ? "Create a new chat to begin..." : "Ask a question based on the documents..."}
                className="flex-1 bg-transparent border-none py-4 px-6 text-slate-100 placeholder-slate-500 focus:outline-none focus:ring-0 disabled:opacity-50"
              />
              <button
                onClick={handleSend}
                disabled={!input.trim() || activeSessionId === null}
                className="p-4 text-indigo-400 hover:text-indigo-300 disabled:text-slate-600 disabled:hover:text-slate-600 transition-colors"
              >
                <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor" className="w-6 h-6">
                  <path d="M3.478 2.404a.75.75 0 00-.926.941l2.432 7.905H13.5a.75.75 0 010 1.5H4.984l-2.432 7.905a.75.75 0 00.926.94 60.519 60.519 0 0018.445-8.986.75.75 0 000-1.218A60.517 60.517 0 003.478 2.404z" />
                </svg>
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
