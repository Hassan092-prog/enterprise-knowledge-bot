"use client";

import { useState, useRef, useEffect } from "react";

type Message = {
  role: "user" | "assistant";
  content: string;
};

type Document = [string, number]; // [filename, page] (if we get it in that format, or just string if it's the filename)

export default function Home() {
  const [messages, setMessages] = useState<Message[]>([
    { role: "assistant", content: "Hello! Upload some documents and ask me anything about them." },
  ]);
  const [input, setInput] = useState("");
  const [documents, setDocuments] = useState<string[]>([]);
  const [isUploading, setIsUploading] = useState(false);
  const [isTyping, setIsTyping] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  // Auto-scroll to bottom of chat
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  // Fetch documents on load
  useEffect(() => {
    fetchDocuments();
  }, []);

  const fetchDocuments = async () => {
    try {
      const res = await fetch("http://localhost:8000/documents");
      if (res.ok) {
        const data = await res.json();
        setDocuments(data.documents || []);
      }
    } catch (error) {
      console.error("Failed to fetch documents:", error);
    }
  };

  const handleUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    setIsUploading(true);
    const formData = new FormData();
    formData.append("file", file);

    try {
      const res = await fetch("http://localhost:8000/upload", {
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
      const res = await fetch(`http://localhost:8000/documents/${filename}`, {
        method: "DELETE",
      });
      if (res.ok) {
        await fetchDocuments();
      }
    } catch (error) {
      console.error("Delete error:", error);
    }
  };

  const handleSend = async () => {
    if (!input.trim()) return;

    const userQuery = input.trim();
    setInput("");
    setMessages((prev) => [...prev, { role: "user", content: userQuery }]);
    setIsTyping(true);

    // Placeholder for assistant response
    setMessages((prev) => [...prev, { role: "assistant", content: "" }]);

    try {
      const res = await fetch("http://localhost:8000/query", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query: userQuery }),
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
        <div className="p-6 border-b border-slate-800 bg-slate-900/50 backdrop-blur">
          <h1 className="text-xl font-bold bg-gradient-to-r from-indigo-400 to-cyan-400 bg-clip-text text-transparent">
            Enterprise RAG Bot
          </h1>
          <p className="text-sm text-slate-500 mt-1">Multi-format knowledge base</p>
        </div>

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
          <p className="text-xs text-slate-500 text-center mt-3">
            Supports PDF, DOCX, TXT, CSV
          </p>
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
                <div className="whitespace-pre-wrap leading-relaxed text-sm md:text-base">
                  {msg.content}
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
                placeholder="Ask a question based on the documents..."
                className="flex-1 bg-transparent border-none py-4 px-6 text-slate-100 placeholder-slate-500 focus:outline-none focus:ring-0"
              />
              <button
                onClick={handleSend}
                disabled={!input.trim()}
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
