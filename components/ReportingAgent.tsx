import React, { useState, useRef, useEffect } from 'react';
import Terminal, { LogEntry } from './Terminal';
import mermaid from 'mermaid';
import { supabase, useAuth } from '../contexts/AuthContext';
import { useNavigate } from 'react-router-dom';

mermaid.initialize({ startOnLoad: false, theme: 'dark' });

// --- Types & Interfaces ---
export type TaskType = 'summary' | 'report';
export type InputMode = 'text_only' | 'document_based';
export type AgentWorkflowStatus = 'idle' | 'validating' | 'normalizing' | 'generating' | 'refining' | 'completed' | 'ambiguous' | 'low_signal' | 'error';

export interface DocumentMetadata {
  attached: boolean;
  file_type: 'pdf' | 'docx' | 'txt' | 'none';
  file_name: string | null;
  size?: number;
}

export interface Constraints {
  hallucination_allowed: boolean;
  output_structure_required: boolean;
}

export interface NormalizedIntent {
  request_id: string;
  task_type: TaskType;
  input_mode: InputMode;
  user_prompt: string;
  detected_category: string;
  document_metadata: DocumentMetadata;
  content_scope: string;
  confidence_score: number;
  is_ambiguous: boolean;
  is_supported: boolean;
  constraints: Constraints;
  timestamp: string;
}

export interface CustomSection {
  title: string;
  content: string;
  image_keyword?: string;
}

export interface ReportContent {
  hero_image_keyword: string;
  executive_summary: string;
  highlights: string[];
  risks_and_blockers: string[];
  actions_required: string[];
  evidence_links: string[];
  diagrams: { title: string; mermaid_code: string }[];
  additional_sections: CustomSection[];
}

export interface FinalReportJSON {
  request_id: string;
  status: 'completed' | 'failed' | 'cached';
  report: ReportContent;
  source_type: 'text' | 'document';
  confidence_level: 'high' | 'medium' | 'low';
  generated_at: string;
}

export interface ValidationError {
  status: 'error';
  error_type: string;
  message: string;
}

export type FeedbackAction = 'apply_correction' | 'consolidate';

export interface AgentStateResponse {
  thread_id: string;
  status: 'in_progress' | 'needs_clarification' | 'rejected_low_signal' | 'completed' | 'error';
  clarification_question?: string | null;
  rejection_reason?: string | null;
  intent?: NormalizedIntent | null;
  report?: FinalReportJSON | null;
  memory?: string;
  error?: ValidationError;
}

// --- Services & Logger ---

export type LogType = 'info' | 'warn' | 'error' | 'success' | 'api' | 'db' | 'guardrail';

class Logger {
  private listeners: ((entry: LogEntry) => void)[] = [];

  log(message: string, type: LogType = 'info', payload?: any) {
    const entry: LogEntry = {
      id: `log_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`,
      timestamp: new Date().toLocaleTimeString(),
      type,
      message,
      payload
    };

    const style = this.getConsoleStyle(type);
    console.log(`%c[${entry.timestamp}] [${type.toUpperCase()}] ${message}`, style, payload || '');
    this.listeners.forEach(l => l(entry));
  }

  subscribe(listener: (entry: LogEntry) => void) {
    this.listeners.push(listener);
    return () => {
      this.listeners = this.listeners.filter(l => l !== listener);
    };
  }

  private getConsoleStyle(type: LogType): string {
    switch (type) {
      case 'api': return 'color: #818cf8; font-weight: bold;';
      case 'success': return 'color: #10b981; font-weight: bold;';
      case 'error': return 'color: #ef4444; font-weight: bold;';
      case 'warn': return 'color: #f59e0b; font-weight: bold;';
      case 'db': return 'color: #ec4899; font-weight: bold;';
      default: return 'color: #64748b;';
    }
  }
}

const logger = new Logger();

const API_BASE_URL = import.meta.env.VITE_API_URL || "http://localhost:8000";

async function getAuthToken() {
  const { data } = await supabase.auth.getSession();
  return data.session?.access_token || '';
}

class GeminiReportingService {
  async runAgent(payload: {
    thread_id?: string;
    prompt: string;
    document?: {
      fileBase64?: string | null;
      fileName?: string | null;
      fileSize?: number | null;
      mimeType?: string | null;
    };
  }): Promise<AgentStateResponse> {
    logger.log("LangGraph: Running /agent/run", "api");
    const token = await getAuthToken();
    const response = await fetch(`${API_BASE_URL}/agent/run`, {
      method: "POST",
      headers: { 
        "Content-Type": "application/json",
        "Authorization": `Bearer ${token}`
      },
      body: JSON.stringify(payload),
    });
    if (!response.ok) {
      const err = await response.json();
      throw new Error(err.detail || "Agent run failed.");
    }
    return await response.json();
  }

  async sendFeedback(payload: {
    thread_id: string;
    feedback_action: FeedbackAction;
    next_suggestion?: string;
    feedback_score?: number;
  }): Promise<AgentStateResponse> {
    logger.log("LangGraph: Running /agent/feedback", "api");
    const token = await getAuthToken();
    const response = await fetch(`${API_BASE_URL}/agent/feedback`, {
      method: "POST",
      headers: { 
        "Content-Type": "application/json",
        "Authorization": `Bearer ${token}`
      },
      body: JSON.stringify(payload),
    });
    if (!response.ok) {
      const err = await response.json();
      throw new Error(err.detail || "Feedback failed.");
    }
    return await response.json();
  }
}

class DatabaseService {
  private cache = new Map<string, FinalReportJSON>();

  async storeInitialIntent(intent: NormalizedIntent): Promise<void> {
    logger.log(`Logging initial intent: ${intent.request_id}`, "db");
  }

  async getPreferences(category: string): Promise<string> {
    logger.log(`Fetching rules for domain: ${category}`, "db");
    try {
      const token = await getAuthToken();
      const response = await fetch(`${API_BASE_URL}/preferences/${category}`, {
        headers: { "Authorization": `Bearer ${token}` }
      });
      if (!response.ok) return "Apply standard professional reporting standards.";
      const data = await response.json();
      return data.preference_rules;
    } catch {
      return "Apply standard professional reporting standards.";
    }
  }

  async updatePreference(category: string, rules: string): Promise<void> {
    logger.log(`Updating memory for category: ${category}`, "db");
  }

  async storeInteractionSummary(requestId: string, category: string, summary: string, score: number): Promise<void> {
    logger.log(`Persisting interaction audit log for ${requestId}`, "db");
    try {
      const token = await getAuthToken();
      await fetch(`${API_BASE_URL}/store-interaction`, {
        method: "POST",
        headers: { 
          "Content-Type": "application/json",
          "Authorization": `Bearer ${token}`
        },
        body: JSON.stringify({ requestId, category, summary, score }),
      });
    } catch (e) {
      logger.log("Outcome summary logging failed", "warn", e);
    }
  }

  getRequestHash(prompt: string, fileName: string | null, size: number): string {
    const raw = `${prompt}:${fileName || 'none'}:${size}`;
    let hash = 0;
    for (let i = 0; i < raw.length; i++) {
      hash = (hash << 5) - hash + raw.charCodeAt(i);
      hash |= 0;
    }
    return `h_${hash}`;
  }

  getCachedReport(hash: string): FinalReportJSON | null {
    return this.cache.get(hash) || null;
  }

  setCachedReport(hash: string, report: FinalReportJSON): void {
    this.cache.set(hash, report);
  }
}

const gemini = new GeminiReportingService();
const db = new DatabaseService();

// --- Components ---

const MermaidDiagram = ({ chart }: { chart: string }) => {
  const containerRef = useRef<HTMLDivElement>(null);
  
  useEffect(() => {
    if (containerRef.current && chart) {
      const cleanChart = chart.replace(/```mermaid/g, '').replace(/```/g, '').trim();
      mermaid.render(`mermaid-${Math.random().toString(36).substring(7)}`, cleanChart).then((result) => {
        if (containerRef.current) containerRef.current.innerHTML = result.svg;
      }).catch(e => console.error("Mermaid error", e));
    }
  }, [chart]);

  return <div ref={containerRef} className="flex justify-center overflow-x-auto my-6 p-6 bg-slate-950/50 rounded-2xl border border-slate-800/50 shadow-inner" />;
};

const FormattedText = ({ text }: { text: string }) => {
  if (!text) return null;
  const processed = text
    .replace(/\*\*(.*?)\*\*/g, '<strong class="font-bold text-indigo-400">$1</strong>')
    .replace(/\^([0-9a-zA-Z]+)/g, '<sup class="text-[0.6em] font-bold">$1</sup>')
    .replace(/_([0-9a-zA-Z]+)/g, '<sub class="text-[0.6em] font-bold">$1</sub>');
  return <span dangerouslySetInnerHTML={{ __html: processed }} />;
};

const ReportingAgent: React.FC = () => {
  const [view, setView] = useState<'agent' | 'architecture'>('agent');
  const [prompt, setPrompt] = useState('');
  const [suggestion, setSuggestion] = useState('');
  const [file, setFile] = useState<File | null>(null);
  const [fileBase64, setFileBase64] = useState<string>('');
  const [isFileReading, setIsFileReading] = useState(false);
  const [status, setStatus] = useState<AgentWorkflowStatus>('idle');
  const [error, setError] = useState<ValidationError | null>(null);
  const [memory, setMemory] = useState<string>('Standard Protocols');
  const [isTerminalOpen, setIsTerminalOpen] = useState(false);
  const [threadId, setThreadId] = useState<string | null>(null);
  const [intent, setIntent] = useState<NormalizedIntent | null>(null);
  const [reportJSON, setReportJSON] = useState<FinalReportJSON | null>(null);
  const [history, setHistory] = useState<string[]>([]);
  const [isFinalizing, setIsFinalizing] = useState(false);
  const [showLearnSuccess, setShowLearnSuccess] = useState(false);
  const [showLargeWarning, setShowLargeWarning] = useState(false);
  const [clarificationQuestion, setClarificationQuestion] = useState<string | null>(null);
  const [rejectionReason, setRejectionReason] = useState<string | null>(null);

  const { profile } = useAuth();
  const navigate = useNavigate();

  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleExportPDF = async () => {
    const element = document.getElementById('report-container');
    if (!element) return;
    // @ts-ignore
    const html2pdf = (await import('html2pdf.js')).default;
    const opt = {
      margin:       [0.5, 0.5, 0.5, 0.5],
      filename:     `Report_${intent?.request_id || 'export'}.pdf`,
      image:        { type: 'jpeg', quality: 0.98 },
      html2canvas:  { scale: 2, useCORS: true },
      jsPDF:        { unit: 'in', format: 'letter', orientation: 'portrait' }
    };
    html2pdf().from(element).set(opt).save();
  };

  useEffect(() => {
    db.getPreferences('general').then(setMemory);
  }, []);

  const readFileAsBase64 = (selectedFile: File): Promise<string> => {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => {
        const result = reader.result as string;
        resolve(result.includes(',') ? result.split(',')[1] : btoa(result));
      };
      reader.onerror = () => reject(reader.error || new Error("Unable to read the selected file."));
      reader.readAsDataURL(selectedFile);
    });
  };

  const processSelectedFile = async (selectedFile?: File | null) => {
    if (!selectedFile || isBusy) return;

    const ext = selectedFile.name.split('.').pop()?.toLowerCase();
    if (!['pdf', 'txt', 'docx'].includes(ext || '')) {
      logger.log("Guardrail: Blocked unsupported file format", "guardrail", { ext });
      setError({ status: 'error', error_type: 'INVALID_FORMAT', message: "Resource Policy: Only .pdf, .txt, and .docx allowed." });
      setFile(null);
      setFileBase64('');
      if (fileInputRef.current) fileInputRef.current.value = '';
      return;
    }

    setError(null);
    setFile(selectedFile);
    setFileBase64('');
    setShowLargeWarning(selectedFile.size > 10 * 1024 * 1024);
    setIsFileReading(true);

    try {
      const encoded = await readFileAsBase64(selectedFile);
      setFileBase64(encoded);
      logger.log("Source asset loaded successfully", "success", {
        fileName: selectedFile.name,
        fileSize: selectedFile.size,
      });
    } catch (err: any) {
      logger.log("File read failed", "error", err);
      setFile(null);
      setFileBase64('');
      setError({
        status: 'error',
        error_type: 'INVALID_FORMAT',
        message: err?.message || "Unable to read the selected file. Please try another document.",
      });
      if (fileInputRef.current) fileInputRef.current.value = '';
    } finally {
      setIsFileReading(false);
    }
  };

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    processSelectedFile(e.target.files?.[0]);
  };

  const handleDrop = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    e.stopPropagation();
    processSelectedFile(e.dataTransfer.files?.[0]);
  };

  const preventFileNavigation = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    e.stopPropagation();
  };

  const executeInitial = async () => {
    if (!prompt.trim() && !file) {
      setError({ status: 'error', error_type: 'INVALID_PROMPT', message: "Guardrail: Please provide a prompt or a document to analyze." });
      return;
    }
    if (file && (isFileReading || !fileBase64)) {
      setError({ status: 'error', error_type: 'MISSING_DOCUMENT', message: "Please wait for the document to finish loading before starting synthesis." });
      return;
    }
    setError(null);
    setShowLearnSuccess(false);

    const hash = db.getRequestHash(prompt, file?.name || null, file?.size || 0);
    const cached = db.getCachedReport(hash);
    if (cached) {
      logger.log("Guardrail: Cache hit. Serving duplicate request.", "guardrail");
      setReportJSON({ ...cached, status: 'cached' });
      setStatus('completed');
      return;
    }

    setStatus('validating');
    try {
      setIntent(null);
      setReportJSON(null);

      const mimeType = file ? (file.name.toLowerCase().endsWith('.pdf') ? 'application/pdf' : 'text/plain') : null;

      const res = await gemini.runAgent({
        thread_id: threadId ?? undefined,
        prompt,
        document: file
          ? {
              fileBase64: fileBase64 || null,
              fileName: file.name,
              fileSize: file.size,
              mimeType,
            }
          : undefined,
      });

      setThreadId(res.thread_id || null);

      if (res.status === 'needs_clarification') {
        setStatus('ambiguous');
        setIntent(res.intent || null);
        setClarificationQuestion(res.clarification_question ?? null);
        setRejectionReason(null);
        return;
      }

      if (res.status === 'rejected_low_signal') {
        setStatus('low_signal');
        setIntent(res.intent || null);
        setRejectionReason(res.rejection_reason ?? null);
        setClarificationQuestion(null);
        return;
      }

      if (res.status === 'completed' && res.report) {
        setIntent(res.intent || null);
        setMemory(res.memory || memory);
        setReportJSON(res.report);
        db.setCachedReport(hash, res.report);
        setStatus('completed');
        return;
      }

      if (res.status === 'error' && res.error) {
        setError(res.error);
        setStatus('error');
        return;
      }

      setError({ status: 'error', error_type: 'INVALID_FORMAT', message: "Agent returned an unexpected state." });
      setStatus('error');
    } catch (err: any) {
      const msg: string = err.message || 'Unknown error';
      let errType = 'UNSUPPORTED_TASK';
      let errMsg = msg;
      if (msg.includes('Failed to fetch') || msg.includes('NetworkError') || msg.includes('ECONNREFUSED')) {
        errType = 'BACKEND_OFFLINE';
        errMsg = 'Cannot connect to backend at localhost:8000. Please ensure the Python server is running (cd backend && uvicorn main:app --reload).';
      } else if (msg.includes('IRRELEVANT')) {
        errType = 'IRRELEVANT';
      } else if (msg.includes('QUOTA') || msg.includes('429') || msg.includes('quota')) {
        errType = 'QUOTA_EXCEEDED';
        errMsg = 'Gemini API quota exceeded. Please wait a moment and try again.';
      }
      setError({ status: 'error', error_type: errType, message: errMsg });
      setStatus('error');
    }
  };

  const resetAgent = (full: boolean = true) => {
    if (full) {
      setPrompt('');
      setFile(null);
      setFileBase64('');
      setIsFileReading(false);
      setIntent(null);
      setThreadId(null);
      setShowLargeWarning(false);
      setClarificationQuestion(null);
      setRejectionReason(null);
      if (fileInputRef.current) fileInputRef.current.value = '';
    }
    setSuggestion('');
    setStatus('idle');
    setError(null);
    setReportJSON(null);
    setHistory([]);
  };

  const isBusy = ['validating', 'normalizing', 'generating', 'refining'].includes(status);

  return (
    <div className="flex flex-col h-screen font-sans antialiased bg-[#0f172a] text-slate-300 overflow-hidden">
      {/* Dynamic Background */}
      <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_top_right,_var(--tw-gradient-stops))] from-indigo-900/20 via-[#0f172a] to-[#0f172a] pointer-events-none" />

      {/* Header */}
      <header className="relative z-20 bg-slate-900/50 backdrop-blur-xl border-b border-slate-800/60 px-8 py-5 flex items-center justify-between shadow-2xl">
        <div className="flex items-center gap-4">
          <div className="w-12 h-12 bg-gradient-to-br from-indigo-500 to-purple-600 rounded-2xl flex items-center justify-center text-white shadow-lg shadow-indigo-500/20 ring-1 ring-white/10">
            <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2.5" d="M13 10V3L4 14h7v7l9-11h-7z" /></svg>
          </div>
          <div>
            <h1 className="text-xl font-black text-white tracking-tight leading-none uppercase">Reporting Agent</h1>
            <p className="text-[10px] text-indigo-400 font-bold uppercase tracking-[0.2em] mt-1 flex items-center gap-2">
              <span className="w-2 h-2 bg-emerald-400 rounded-full animate-pulse shadow-[0_0_8px_rgba(52,211,153,0.8)]"></span>
              Sentinel Guardrails Active
            </p>
          </div>
        </div>
        <div className="flex items-center gap-4">
          <button onClick={() => setIsTerminalOpen(!isTerminalOpen)} className={`px-5 py-2.5 text-[10px] font-black uppercase tracking-widest rounded-xl border transition-all duration-300 ${isTerminalOpen ? 'bg-indigo-500/20 text-indigo-300 border-indigo-500/30' : 'bg-slate-800/50 text-slate-400 border-slate-700 hover:bg-slate-800 hover:text-slate-200'}`}>
            Telemetry Stream
          </button>
          <button onClick={() => resetAgent(true)} className="px-5 py-2.5 text-[10px] font-black text-slate-400 hover:text-white bg-slate-800/30 hover:bg-slate-800 border border-slate-800 rounded-xl uppercase tracking-widest transition-all">Reset Session</button>
          {profile?.organization_id && (
            <button onClick={() => navigate('/admin')} className="px-5 py-2.5 text-[10px] font-black text-emerald-400 hover:text-white bg-emerald-500/10 hover:bg-emerald-500 border border-emerald-500/30 rounded-xl uppercase tracking-widest transition-all">
              {profile.role === 'admin' ? 'Admin Panel' : 'Profile'}
            </button>
          )}
          <button onClick={async () => await supabase.auth.signOut()} className="px-5 py-2.5 text-[10px] font-black text-red-400 hover:text-white bg-red-500/10 hover:bg-red-500 border border-red-500/30 rounded-xl uppercase tracking-widest transition-all">Sign Out</button>
        </div>
      </header>

      {/* Main Content Area */}
      <main className={`relative z-10 flex-1 flex flex-col lg:flex-row overflow-hidden transition-all duration-500 ${isTerminalOpen ? 'pb-[33vh]' : ''}`}>
        
        {/* Sidebar: Inputs & Controls */}
        <aside className="w-full lg:w-[460px] bg-slate-900/40 backdrop-blur-md border-r border-slate-800/50 p-8 flex flex-col gap-8 overflow-y-auto shadow-2xl z-10 custom-scrollbar">
          
          {status === 'ambiguous' ? (
            <div className="p-6 bg-amber-500/10 border border-amber-500/20 rounded-3xl space-y-5 animate-in slide-in-from-top-4 backdrop-blur-sm">
              <h3 className="text-sm font-black text-amber-400 uppercase tracking-widest flex items-center gap-2">
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" /></svg>
                Ambiguity Detected
              </h3>
              <p className="text-sm text-amber-200/80 leading-relaxed font-medium">
                {clarificationQuestion ?? "Synthesis confidence is below 40%. Please clarify your specific analytical objective to ensure grounding accuracy."}
              </p>
              <textarea
                className="w-full h-32 p-4 bg-slate-950/50 border border-amber-500/30 rounded-2xl text-sm text-white focus:outline-none focus:border-amber-400 focus:ring-1 focus:ring-amber-400/50 transition-all placeholder:text-slate-600 resize-none"
                placeholder="Ex: Summarize the financial growth specifically for Q4..."
                value={prompt}
                onChange={(e) => setPrompt(e.target.value)}
              />
              <div className="flex gap-3">
                <button onClick={executeInitial} className="flex-1 py-3 bg-amber-500/20 text-amber-300 border border-amber-500/30 rounded-xl font-bold text-[10px] uppercase tracking-widest hover:bg-amber-500/30 transition-all">Retry Context</button>
                <button onClick={() => resetAgent(true)} className="px-4 py-3 bg-slate-800/50 text-slate-400 border border-slate-700/50 rounded-xl font-bold text-[10px] uppercase tracking-widest hover:text-white transition-all">Dismiss</button>
              </div>
            </div>
          ) : status === 'low_signal' ? (
             <div className="p-6 bg-red-500/10 border border-red-500/20 rounded-3xl space-y-5 animate-in slide-in-from-top-4 backdrop-blur-sm text-center">
               <div className="w-12 h-12 bg-red-500/20 rounded-full flex items-center justify-center mx-auto text-red-400 mb-2 ring-1 ring-red-500/30">
                 <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M18.364 18.364A9 9 0 005.636 5.636m12.728 12.728A9 9 0 015.636 5.636m12.728 12.728L5.636 5.636" /></svg>
               </div>
               <h3 className="text-sm font-black text-red-400 uppercase tracking-widest">Insufficient Signal</h3>
               <p className="text-sm text-red-200/80 leading-relaxed font-medium">
                 {rejectionReason ?? "Resource Guardrail: The provided asset lacks sufficient analytical signal for reporting. Please provide a substantive document."}
               </p>
               <button onClick={() => resetAgent(true)} className="w-full py-4 bg-red-500/20 text-red-300 border border-red-500/30 rounded-2xl font-bold text-[10px] uppercase tracking-widest hover:bg-red-500/30 transition-all">Change Source Asset</button>
             </div>
          ) : !reportJSON ? (
            <div className="space-y-8 animate-in fade-in duration-500">
              
              {/* Memory Module */}
              <div className="p-5 bg-indigo-500/5 border border-indigo-500/20 rounded-3xl relative overflow-hidden group">
                <div className="absolute top-0 right-0 w-32 h-32 bg-indigo-500/10 blur-3xl rounded-full group-hover:bg-indigo-500/20 transition-all"></div>
                <div className="relative z-10">
                  <div className="flex items-center gap-2 mb-3">
                    <svg className="w-4 h-4 text-indigo-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M9 3v2m6-2v2M9 19v2m6-2v2M5 9H3m2 6H3m18-6h-2m2 6h-2M7 19h10a2 2 0 002-2V7a2 2 0 00-2-2H7a2 2 0 00-2 2v10a2 2 0 002 2zM9 9h6v6H9V9z" /></svg>
                    <p className="text-[10px] font-black uppercase tracking-[0.2em] text-indigo-400">Domain Memory State</p>
                  </div>
                  <p className="text-xs font-mono leading-relaxed text-slate-400 italic line-clamp-3">"{memory}"</p>
                </div>
              </div>

              {/* Input: Prompt */}
              <div className="space-y-3">
                <h3 className="text-[10px] font-black text-slate-500 uppercase tracking-[0.2em] ml-2">Analytical Objective</h3>
                <div className="relative group">
                  <textarea
                    className="w-full h-40 p-5 bg-slate-950/50 border border-slate-700/50 rounded-3xl text-sm text-white focus:outline-none focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500/50 transition-all placeholder:text-slate-600 resize-none shadow-inner"
                    placeholder="Describe your reporting goal in detail..."
                    value={prompt}
                    disabled={isBusy}
                    onChange={(e) => setPrompt(e.target.value)}
                  />
                  <div className="absolute inset-0 rounded-3xl ring-1 ring-white/5 pointer-events-none group-hover:ring-white/10 transition-all"></div>
                </div>
              </div>

              {/* Input: File */}
              <div className="space-y-3">
                <h3 className="text-[10px] font-black text-slate-500 uppercase tracking-[0.2em] ml-2">Source Material (.pdf, .txt, .docx)</h3>
                <div
                  onClick={() => !isBusy && fileInputRef.current?.click()}
                  onDragEnter={preventFileNavigation}
                  onDragOver={preventFileNavigation}
                  onDragLeave={preventFileNavigation}
                  onDrop={handleDrop}
                  className={`relative overflow-hidden group border-2 border-dashed rounded-3xl p-8 text-center transition-all duration-300 ${file ? 'border-indigo-500/50 bg-indigo-500/5' : 'border-slate-700/50 hover:border-indigo-500/40 cursor-pointer hover:bg-slate-800/30'}`}
                >
                  <div className="relative z-10 flex flex-col items-center gap-3">
                    {file ? (
                      <>
                        <div className="w-10 h-10 bg-indigo-500/20 rounded-full flex items-center justify-center text-indigo-400">
                          <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" /></svg>
                        </div>
                        <div>
                          <span className="text-sm font-bold text-slate-200 block">{file.name}</span>
                          <span className="text-[10px] text-slate-500 uppercase font-bold">
                            {isFileReading ? 'Loading document...' : `${(file.size / 1024).toFixed(1)} KB ready`}
                          </span>
                        </div>
                      </>
                    ) : (
                      <>
                        <div className="w-12 h-12 bg-slate-800/50 rounded-full flex items-center justify-center text-slate-500 group-hover:text-indigo-400 group-hover:scale-110 transition-all duration-300">
                           <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12" /></svg>
                        </div>
                        <span className="text-[11px] font-black text-slate-400 uppercase tracking-widest group-hover:text-slate-300 transition-colors">Drop Asset or Browse</span>
                      </>
                    )}
                  </div>
                  <input type="file" ref={fileInputRef} onChange={handleFileChange} className="hidden" accept=".txt,.pdf,.docx" />
                  {showLargeWarning && (
                     <div className="absolute bottom-2 left-0 right-0 text-center">
                        <span className="px-3 py-1 bg-amber-500/20 text-amber-400 rounded-full text-[9px] font-black uppercase tracking-widest border border-amber-500/30">Large File Target</span>
                     </div>
                  )}
                </div>
              </div>

              {/* Execute Button */}
              <button
                onClick={executeInitial}
                disabled={isBusy || isFileReading}
                className={`relative w-full py-5 rounded-3xl font-black text-[12px] uppercase tracking-[0.2em] overflow-hidden transition-all duration-300 ${isBusy || isFileReading ? 'bg-slate-800/50 text-slate-500 cursor-not-allowed' : 'bg-gradient-to-r from-indigo-600 to-purple-600 text-white hover:shadow-[0_0_30px_rgba(79,70,229,0.3)] hover:scale-[1.02] active:scale-[0.98]'}`}
              >
                {isBusy || isFileReading ? (
                  <span className="flex items-center justify-center gap-3">
                    <svg className="animate-spin -ml-1 mr-3 h-4 w-4 text-slate-400" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24"><circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle><path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path></svg>
                    {isFileReading ? 'Loading Document...' : 'Synthesizing...'}
                  </span>
                ) : 'Initialize Synthesis'}
                {!isBusy && !isFileReading && <div className="absolute inset-0 bg-white/20 translate-y-full hover:translate-y-0 transition-transform duration-300"></div>}
              </button>
            </div>
          ) : (
            <div className="space-y-8 animate-in fade-in slide-in-from-left-4 duration-500">
               {/* Post-Generation Controls */}
               <div className="flex items-center justify-between p-4 bg-slate-900/50 border border-slate-700/50 rounded-2xl">
                 <div className="flex items-center gap-3">
                    <div className={`w-2 h-2 rounded-full ${reportJSON.status === 'cached' ? 'bg-emerald-400' : 'bg-indigo-400'} animate-pulse`}></div>
                    <span className="text-[10px] font-black uppercase tracking-widest text-slate-400">{reportJSON.status === 'cached' ? 'Served from Cache' : 'Synthesis Complete'}</span>
                 </div>
                 <span className={`text-[10px] font-black uppercase tracking-widest px-3 py-1 rounded-full border ${reportJSON.confidence_level === 'high' ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20' : reportJSON.confidence_level === 'medium' ? 'bg-amber-500/10 text-amber-400 border-amber-500/20' : 'bg-red-500/10 text-red-400 border-red-500/20'}`}>
                   Conf: {reportJSON.confidence_level}
                 </span>
               </div>

               <div className="space-y-3">
                <h3 className="text-[10px] font-black text-slate-500 uppercase tracking-[0.2em] ml-2">Override / Refine Strategy</h3>
                <textarea
                  className="w-full h-32 p-4 bg-slate-950/50 border border-slate-700/50 rounded-2xl text-sm text-white focus:outline-none focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500/50 transition-all placeholder:text-slate-600 resize-none shadow-inner"
                  placeholder="E.g., Make it more concise, focus only on risks..."
                  value={suggestion}
                  disabled={isBusy}
                  onChange={(e) => setSuggestion(e.target.value)}
                />
              </div>

              <div className="space-y-3">
                 <button
                  onClick={async () => {
                    if (!reportJSON || !intent || !suggestion || !threadId) return;
                    setStatus('refining');
                    try {
                      const res = await gemini.sendFeedback({
                        thread_id: threadId,
                        feedback_action: 'apply_correction',
                        next_suggestion: suggestion,
                      });

                      if (res.status === 'completed' && res.report) {
                        setHistory(prev => [...prev, suggestion]);
                        setReportJSON(res.report);
                        setMemory(res.memory || memory);
                        setSuggestion('');
                        setStatus('completed');
                        return;
                      }
                      if (res.status === 'error' && res.error) {
                        setError(res.error);
                        setStatus('error');
                        return;
                      }
                      throw new Error("Refinement cycle error.");
                    } catch (err: any) {
                      setError({ status: 'error', error_type: 'INVALID_FORMAT', message: err.message || "Refinement cycle error." });
                      setStatus('error');
                    }
                  }}
                  disabled={isBusy || !suggestion || !threadId}
                  className={`w-full py-4 rounded-2xl font-black text-[11px] uppercase tracking-widest transition-all ${isBusy || !suggestion ? 'bg-slate-800/50 text-slate-600' : 'bg-indigo-600 text-white hover:bg-indigo-500 shadow-[0_0_15px_rgba(79,70,229,0.3)]'}`}
                >
                  Force Correction
                </button>
                <button
                  onClick={async () => {
                    if (!reportJSON || !intent || !threadId) return;
                    setIsFinalizing(true);
                    try {
                      const res = await gemini.sendFeedback({
                        thread_id: threadId,
                        feedback_action: 'consolidate',
                        feedback_score: 1,
                      });

                      if (res.status === 'completed') {
                        setMemory(res.memory || memory);
                        setShowLearnSuccess(true);
                        setTimeout(() => setShowLearnSuccess(false), 5000);
                        resetAgent(true);
                        return;
                      }
                      if (res.status === 'error' && res.error) {
                        setError(res.error);
                        setStatus('error');
                        return;
                      }
                      throw new Error("Consolidation error.");
                    } catch (err) {
                      setError({ status: 'error', error_type: 'INVALID_FORMAT', message: "Memory consolidation failed." });
                      setStatus('error');
                    } finally {
                      setIsFinalizing(false);
                    }
                  }}
                  disabled={isFinalizing || isBusy || !threadId}
                  className="w-full py-4 bg-slate-800/50 border border-emerald-500/30 text-emerald-400 rounded-2xl font-black text-[11px] uppercase tracking-widest hover:bg-emerald-500/10 hover:border-emerald-500/50 transition-all"
                >
                  {isFinalizing ? 'Consolidating Rules...' : 'Evolve Domain Laws'}
                </button>
                <button
                  onClick={handleExportPDF}
                  className="w-full py-4 bg-slate-800/50 border border-slate-700/50 text-slate-300 rounded-2xl font-black text-[11px] uppercase tracking-widest hover:bg-slate-700/50 hover:text-white transition-all flex items-center justify-center gap-2"
                >
                  <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" /></svg>
                  Export as PDF
                </button>
              </div>
            </div>
          )}
        </aside>

        {/* Main Report Canvas */}
        <section className="flex-1 overflow-y-auto bg-slate-950/50 p-6 md:p-12 lg:p-20 relative custom-scrollbar">
          
          {showLearnSuccess && (
            <div className="absolute top-8 left-1/2 -translate-x-1/2 z-50 bg-emerald-500/20 backdrop-blur-md border border-emerald-500/50 text-emerald-300 px-6 py-3 rounded-full font-black text-[10px] uppercase tracking-[0.2em] shadow-[0_0_30px_rgba(16,185,129,0.2)] animate-in slide-in-from-top-4 duration-500 flex items-center gap-3">
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M5 13l4 4L19 7" /></svg>
              Style Laws Solidified for Domain
            </div>
          )}

          {error ? (
            <div className="max-w-2xl mx-auto mt-20 bg-slate-900/50 backdrop-blur-xl border border-red-500/20 rounded-[3rem] p-16 text-center shadow-2xl animate-in zoom-in-95">
              <div className="w-20 h-20 bg-red-500/10 rounded-full flex items-center justify-center mx-auto mb-8 text-red-400 shadow-[0_0_30px_rgba(239,68,68,0.2)]">
                <svg className="w-10 h-10" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" /></svg>
              </div>
              <h2 className="text-2xl font-black text-white mb-4 uppercase tracking-widest">{error.error_type} Fault</h2>
              <p className="text-slate-400 text-sm mb-12 leading-relaxed font-medium max-w-md mx-auto">{error.message}</p>
              <button onClick={() => resetAgent(true)} className="px-10 py-4 bg-slate-800 text-white border border-slate-700 rounded-2xl font-black text-[11px] uppercase tracking-widest hover:bg-slate-700 transition-colors shadow-lg">Acknowledge & Reset</button>
            </div>
          ) : reportJSON ? (
            <div className="max-w-5xl mx-auto pb-24">
              <div id="report-container" className="bg-slate-900/60 backdrop-blur-2xl rounded-[3rem] shadow-2xl shadow-black/50 border border-slate-700/50 overflow-hidden relative animate-in fade-in slide-in-from-bottom-8 duration-700">
                
                {/* Hero Banner Section */}
                <div className="relative h-64 md:h-80 w-full overflow-hidden bg-slate-800">
                  <div className="absolute inset-0 bg-gradient-to-t from-slate-900/90 via-slate-900/40 to-transparent z-10" />
                  <img 
                    src={`https://loremflickr.com/1200/600/${reportJSON.report.hero_image_keyword || 'business'}?lock=${intent?.request_id || '123'}`}
                    alt="Report Hero" 
                    className="absolute inset-0 w-full h-full object-cover opacity-60 mix-blend-overlay"
                    onError={(e) => {
                      (e.target as HTMLImageElement).src = 'https://loremflickr.com/1200/600/abstract';
                    }}
                  />
                  <div className="absolute bottom-8 left-10 md:left-16 z-20">
                    <div className="flex items-center gap-3 mb-4">
                      <span className="text-[10px] font-black uppercase text-indigo-300 bg-indigo-500/20 backdrop-blur-md px-4 py-1.5 rounded-full border border-indigo-500/30 shadow-lg">
                        {intent?.detected_category || 'Analysis'}
                      </span>
                      <span className="text-[10px] font-black uppercase text-emerald-300 bg-emerald-500/20 backdrop-blur-md px-4 py-1.5 rounded-full border border-emerald-500/30 shadow-lg flex items-center gap-1.5">
                        <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="3" d="M5 13l4 4L19 7" /></svg>
                        Fact-Checked
                      </span>
                    </div>
                    <h2 className="text-4xl md:text-5xl font-black text-white tracking-tighter leading-tight drop-shadow-2xl">
                      {intent?.detected_category || 'Intelligence Synthesis'}
                    </h2>
                    <p className="text-xs text-slate-300 font-bold uppercase tracking-[0.2em] mt-4 opacity-80">
                      ID: {intent?.request_id} • Scope: {intent?.content_scope || 'General'}
                    </p>
                  </div>
                </div>

                {/* Report Content */}
                <article className="p-10 md:p-16 lg:px-20 space-y-16 relative z-20 bg-slate-900/40">

                  {/* Executive Summary */}
                  {reportJSON.report.executive_summary === "Not Found." ? (
                    <div className="p-8 bg-amber-500/10 border border-amber-500/20 rounded-3xl text-center">
                      <p className="text-amber-400 font-bold tracking-wide">Grounding Guardrail: Synthesis inhibited. Zero direct evidence found in source assets.</p>
                    </div>
                  ) : (
                    <div className="space-y-6 animate-in slide-in-from-bottom-4 delay-150 fill-mode-both">
                      <div className="flex items-center gap-4">
                        <div className="h-px bg-gradient-to-r from-transparent via-indigo-500/50 to-transparent flex-1" />
                        <h4 className="text-[11px] font-black text-indigo-400 uppercase tracking-[0.3em] flex items-center gap-2">
                          <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2.5" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" /></svg>
                          Executive Summary
                        </h4>
                        <div className="h-px bg-gradient-to-r from-transparent via-indigo-500/50 to-transparent flex-1" />
                      </div>
                      <div className="text-lg md:text-xl text-slate-300 leading-[1.8] font-medium tracking-tight whitespace-pre-line text-justify px-4">
                        <FormattedText text={reportJSON.report.executive_summary} />
                      </div>
                    </div>
                  )}

                  {/* Key Highlights */}
                  {reportJSON.report.highlights?.length > 0 && (
                    <div className="space-y-8 pt-4 animate-in slide-in-from-bottom-4 delay-300 fill-mode-both">
                      <div className="flex items-center gap-4">
                        <div className="h-px bg-gradient-to-r from-transparent via-violet-500/40 to-transparent flex-1" />
                        <h4 className="text-[11px] font-black text-violet-400 uppercase tracking-[0.3em] flex items-center gap-2">
                          <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2.5" d="M13 10V3L4 14h7v7l9-11h-7z" /></svg>
                          Key Findings
                        </h4>
                        <div className="h-px bg-gradient-to-r from-transparent via-violet-500/40 to-transparent flex-1" />
                      </div>
                      <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
                        {reportJSON.report.highlights.map((h, i) => (
                          <div key={i} className="bg-gradient-to-br from-slate-800/40 to-slate-900/60 border border-slate-700/40 p-6 rounded-2xl flex gap-4 group hover:border-violet-500/30 hover:shadow-[0_0_20px_rgba(139,92,246,0.08)] transition-all duration-300">
                            <div className="flex-shrink-0 w-7 h-7 rounded-xl bg-gradient-to-br from-indigo-500/30 to-violet-500/30 text-indigo-300 flex items-center justify-center text-[11px] font-black border border-indigo-500/20 mt-0.5">{i + 1}</div>
                            <p className="text-[14px] text-slate-300 leading-relaxed font-medium group-hover:text-slate-200 transition-colors"><FormattedText text={h} /></p>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}

                  {/* Additional Sections */}
                  {reportJSON.report.additional_sections?.map((section, idx) => (
                    <div key={idx} className="space-y-6 animate-in slide-in-from-bottom-4 fill-mode-both">
                      <div className="flex items-center gap-4">
                        <div className="h-px bg-gradient-to-r from-transparent via-slate-600/60 to-transparent flex-1" />
                        <h4 className="text-[11px] font-black text-slate-400 uppercase tracking-[0.3em]">{section.title}</h4>
                        <div className="h-px bg-gradient-to-r from-transparent via-slate-600/60 to-transparent flex-1" />
                      </div>
                      <div className="text-lg text-slate-300 leading-[1.8] font-medium tracking-tight whitespace-pre-line px-4"><FormattedText text={section.content} /></div>
                      {section.image_keyword && section.image_keyword !== 'none' && section.image_keyword !== '' && (
                        <div className="mt-6 rounded-2xl overflow-hidden shadow-lg border border-slate-700/50">
                          <img src={`https://loremflickr.com/800/400/${section.image_keyword}?lock=${intent?.request_id}-${idx}`} alt={section.title} className="w-full object-cover" onError={(e) => { (e.target as HTMLImageElement).style.display = 'none'; }} />
                        </div>
                      )}
                    </div>
                  ))}

                  {/* Diagrams */}
                  {reportJSON.report.diagrams?.map((diagram, idx) => (
                    <div key={`diagram-${idx}`} className="space-y-6 animate-in slide-in-from-bottom-4 delay-500 fill-mode-both">
                      <div className="flex items-center gap-4">
                        <div className="h-px bg-gradient-to-r from-transparent via-emerald-500/40 to-transparent flex-1" />
                        <h4 className="text-[11px] font-black text-emerald-400 uppercase tracking-[0.3em] flex items-center gap-2">
                          <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2.5" d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" /></svg>
                          {diagram.title}
                        </h4>
                        <div className="h-px bg-gradient-to-r from-transparent via-emerald-500/40 to-transparent flex-1" />
                      </div>
                      <MermaidDiagram chart={diagram.mermaid_code} />
                    </div>
                  ))}

                  {/* Risks & Blockers */}
                  {reportJSON.report.risks_and_blockers?.length > 0 && (
                    <div className="space-y-6 animate-in slide-in-from-bottom-4 delay-600 fill-mode-both">
                      <div className="flex items-center gap-4">
                        <div className="h-px bg-gradient-to-r from-transparent via-red-500/40 to-transparent flex-1" />
                        <h4 className="text-[11px] font-black text-red-400 uppercase tracking-[0.3em] flex items-center gap-2">
                          <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2.5" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" /></svg>
                          Risks & Blockers
                        </h4>
                        <div className="h-px bg-gradient-to-r from-transparent via-red-500/40 to-transparent flex-1" />
                      </div>
                      <div className="space-y-4">
                        {reportJSON.report.risks_and_blockers.map((risk, i) => (
                          <div key={i} className="flex gap-4 p-5 bg-red-950/20 border border-red-500/20 rounded-2xl hover:border-red-500/35 hover:bg-red-950/30 transition-all duration-300">
                            <div className="flex-shrink-0 w-6 h-6 rounded-lg bg-red-500/20 text-red-400 flex items-center justify-center mt-0.5">
                              <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2.5" d="M12 9v2m0 4h.01" /></svg>
                            </div>
                            <p className="text-[14px] text-red-200/80 leading-relaxed font-medium"><FormattedText text={risk} /></p>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}

                  {/* Actions Required */}
                  {reportJSON.report.actions_required?.length > 0 && (
                    <div className="space-y-6 animate-in slide-in-from-bottom-4 delay-700 fill-mode-both">
                      <div className="flex items-center gap-4">
                        <div className="h-px bg-gradient-to-r from-transparent via-teal-500/40 to-transparent flex-1" />
                        <h4 className="text-[11px] font-black text-teal-400 uppercase tracking-[0.3em] flex items-center gap-2">
                          <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2.5" d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-6 9l2 2 4-4" /></svg>
                          Actions Required
                        </h4>
                        <div className="h-px bg-gradient-to-r from-transparent via-teal-500/40 to-transparent flex-1" />
                      </div>
                      <div className="space-y-3">
                        {reportJSON.report.actions_required.map((action, i) => (
                          <div key={i} className="flex gap-4 p-5 bg-teal-950/20 border border-teal-500/20 rounded-2xl hover:border-teal-500/35 hover:bg-teal-950/30 transition-all duration-300">
                            <div className="flex-shrink-0 w-6 h-6 rounded-full bg-teal-500/20 text-teal-400 flex items-center justify-center text-[10px] font-black border border-teal-500/30 mt-0.5">{i + 1}</div>
                            <p className="text-[14px] text-teal-100/80 leading-relaxed font-medium"><FormattedText text={action} /></p>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}

                  {/* Evidence & Sources */}
                  {reportJSON.report.evidence_links?.filter(l => l && l !== 'N/A' && l.trim() !== '').length > 0 && (
                    <div className="space-y-6 animate-in slide-in-from-bottom-4 delay-700 fill-mode-both pb-6">
                      <div className="flex items-center gap-4">
                        <div className="h-px bg-gradient-to-r from-transparent via-blue-500/40 to-transparent flex-1" />
                        <h4 className="text-[11px] font-black text-blue-400 uppercase tracking-[0.3em] flex items-center gap-2">
                          <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2.5" d="M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.899a4 4 0 005.656 0l4-4a4 4 0 00-5.656-5.656l-1.1 1.1" /></svg>
                          Sources & Evidence
                        </h4>
                        <div className="h-px bg-gradient-to-r from-transparent via-blue-500/40 to-transparent flex-1" />
                      </div>
                      <div className="flex flex-wrap gap-3 px-4">
                        {reportJSON.report.evidence_links.filter(l => l && l !== 'N/A' && l.trim() !== '').map((link, i) => (
                          <a key={i} href={link.startsWith('http') ? link : '#'} target="_blank" rel="noopener noreferrer"
                            className="inline-flex items-center gap-2 px-4 py-2 bg-blue-500/10 text-blue-300 border border-blue-500/25 rounded-xl text-xs font-bold hover:bg-blue-500/20 hover:border-blue-500/40 transition-all duration-200 group">
                            <svg className="w-3 h-3 group-hover:translate-x-0.5 transition-transform" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2.5" d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14" /></svg>
                            {link.length > 50 ? link.substring(0, 50) + '…' : link}
                          </a>
                        ))}
                      </div>
                    </div>
                  )}

                </article>
              </div>
            </div>
          ) : isBusy ? (
            <div className="h-full flex flex-col items-center justify-center relative">
              <div className="absolute inset-0 bg-[radial-gradient(circle_at_center,_var(--tw-gradient-stops))] from-indigo-500/10 via-transparent to-transparent animate-pulse"></div>
              <div className="relative w-32 h-32 flex items-center justify-center mb-8">
                <div className="absolute inset-0 border-2 border-indigo-500/20 rounded-full animate-[ping_3s_ease-in-out_infinite]"></div>
                <div className="absolute inset-4 border-2 border-indigo-500/40 rounded-full animate-[ping_2s_ease-in-out_infinite_0.5s]"></div>
                <div className="w-16 h-16 border-4 border-indigo-500 border-t-transparent rounded-full animate-spin"></div>
                <div className="absolute w-8 h-8 bg-indigo-500 rounded-full blur-xl animate-pulse"></div>
              </div>
              <h2 className="text-indigo-400 font-black uppercase tracking-[0.5em] text-xs relative z-10 drop-shadow-[0_0_10px_rgba(129,140,248,0.8)]">
                Neural Synthesis Engaged
              </h2>
              <p className="text-slate-500 text-[9px] mt-4 font-bold uppercase tracking-[0.3em] relative z-10">
                Extracting • Validating • Formatting
              </p>
            </div>
          ) : (
             <div className="h-full w-full flex flex-col items-center justify-center text-center opacity-20 select-none pointer-events-none px-6">
              <svg className="w-32 h-32 mb-8 text-slate-700" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="1" d="M14 10l-2 1m0 0l-2-1m2 1v2.5M20 7l-2 1m2-1l-2-1m2 1v2.5M14 4l-2-1-2 1M4 7l2-1M4 7l2 1M4 7v2.5M12 21l-2-1m2 1l2-1m-2 1v-2.5M6 18l-2-1v-2.5M18 18l2-1v-2.5" /></svg>
              <h2 className="max-w-full text-3xl md:text-4xl font-black uppercase tracking-[0.35em] text-slate-700 text-center leading-tight">
                Reporting Agent
              </h2>
            </div>
          )}
        </section>
      </main>

      <Terminal isOpen={isTerminalOpen} onClose={() => setIsTerminalOpen(false)} logger={logger} />
    </div>
  );
};

export default ReportingAgent;
