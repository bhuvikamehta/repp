import React, { useEffect, useState, useRef, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext';
import { supabase } from '../contexts/AuthContext';

const API = import.meta.env.VITE_API_URL || 'http://localhost:8000';

interface OrgDoc {
  id: string;
  file_name: string;
  file_type: string;
  file_size: number | null;
  chunk_count: number;
  created_at: string;
}

function formatBytes(bytes: number | null): string {
  if (!bytes) return '—';
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1048576) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1048576).toFixed(1)} MB`;
}

function FileTypeTag({ type }: { type: string }) {
  const colors: Record<string, string> = {
    pdf: 'bg-red-500/20 text-red-400 border-red-500/30',
    docx: 'bg-blue-500/20 text-blue-400 border-blue-500/30',
    txt: 'bg-slate-700 text-slate-400 border-slate-600',
    ipynb: 'bg-amber-500/20 text-amber-400 border-amber-500/30',
  };
  const cls = colors[type] || colors.txt;
  return (
    <span className={`px-2 py-0.5 rounded text-[10px] font-bold uppercase tracking-wider border ${cls}`}>
      {type}
    </span>
  );
}

export default function AdminPanelView() {
  const { profile, session } = useAuth();
  const navigate = useNavigate();
  const [members, setMembers] = useState<any[]>([]);
  const [orgInfo, setOrgInfo] = useState<{ name: string; code: string } | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  // RAG state
  const [docs, setDocs] = useState<OrgDoc[]>([]);
  const [docsLoading, setDocsLoading] = useState(false);
  const [uploadState, setUploadState] = useState<'idle' | 'uploading' | 'success' | 'error'>('idle');
  const [uploadMsg, setUploadMsg] = useState('');
  const [dragOver, setDragOver] = useState(false);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const isAdmin = profile?.role === 'admin';

  // ── Fetch members ────────────────────────────────────────────────────────
  useEffect(() => {
    if (!session) return;
    const fetchMembers = async () => {
      try {
        const res = await fetch(`${API}/api/org/members`, {
          headers: { Authorization: `Bearer ${session.access_token}` },
        });
        if (!res.ok) throw new Error('Failed to fetch members');
        const data = await res.json();
        setMembers(data.members);
        setOrgInfo(data.organization);
      } catch (err: any) {
        setError(err.message);
      } finally {
        setLoading(false);
      }
    };
    fetchMembers();
  }, [session]);

  // ── Fetch RAG docs ───────────────────────────────────────────────────────
  const fetchDocs = useCallback(async () => {
    if (!session) return;
    setDocsLoading(true);
    try {
      const res = await fetch(`${API}/api/rag/documents`, {
        headers: { Authorization: `Bearer ${session.access_token}` },
      });
      if (!res.ok) throw new Error('Failed to fetch documents');
      const data = await res.json();
      setDocs(data.documents || []);
    } catch {
      // silently fail — not critical
    } finally {
      setDocsLoading(false);
    }
  }, [session]);

  useEffect(() => {
    if (session) fetchDocs();
  }, [session, fetchDocs]);

  // ── Upload handler ───────────────────────────────────────────────────────
  const handleUpload = async (file: File) => {
    if (!session) return;
    const allowed = ['application/pdf', 'application/vnd.openxmlformats-officedocument.wordprocessingml.document', 'text/plain', 'text/markdown', 'application/json'];
    const nameOk = /\.(pdf|docx|txt|md|ipynb)$/i.test(file.name);
    if (!nameOk) {
      setUploadState('error');
      setUploadMsg('Unsupported file type. Please upload PDF, DOCX, TXT, or IPYNB.');
      return;
    }

    setUploadState('uploading');
    setUploadMsg(`Uploading "${file.name}"…`);

    const form = new FormData();
    form.append('file', file);

    try {
      const res = await fetch(`${API}/api/rag/documents`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${session.access_token}` },
        body: form,
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || 'Upload failed');
      setUploadState('success');
      setUploadMsg(`"${file.name}" ingested — ${data.chunk_count} chunks embedded.`);
      await fetchDocs();
      setTimeout(() => setUploadState('idle'), 4000);
    } catch (err: any) {
      setUploadState('error');
      setUploadMsg(err.message || 'Upload failed. Please try again.');
    }
  };

  const onFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) handleUpload(file);
    e.target.value = '';
  };

  const onDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(false);
    const file = e.dataTransfer.files?.[0];
    if (file) handleUpload(file);
  };

  // ── Delete handler ───────────────────────────────────────────────────────
  const handleDelete = async (docId: string, fileName: string) => {
    if (!window.confirm(`Remove "${fileName}" from the knowledge base?`)) return;
    if (!session) return;
    setDeletingId(docId);
    try {
      const res = await fetch(`${API}/api/rag/documents/${docId}`, {
        method: 'DELETE',
        headers: { Authorization: `Bearer ${session.access_token}` },
      });
      if (!res.ok) throw new Error('Delete failed');
      setDocs(prev => prev.filter(d => d.id !== docId));
    } catch (err: any) {
      alert(err.message);
    } finally {
      setDeletingId(null);
    }
  };

  // ── Member role / remove ─────────────────────────────────────────────────
  const handleUpdateRole = async (memberId: string, newRole: string) => {
    try {
      const res = await fetch(`${API}/api/org/members/${memberId}/role`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${session?.access_token}` },
        body: JSON.stringify({ role: newRole }),
      });
      if (!res.ok) throw new Error('Failed to update role');
      setMembers(members.map(m => (m.id === memberId ? { ...m, role: newRole } : m)));
    } catch (err: any) {
      alert(err.message);
    }
  };

  const handleRemoveMember = async (memberId: string) => {
    if (!window.confirm('Are you sure you want to remove this member?')) return;
    try {
      const res = await fetch(`${API}/api/org/members/${memberId}`, {
        method: 'DELETE',
        headers: { Authorization: `Bearer ${session?.access_token}` },
      });
      if (!res.ok) throw new Error('Failed to remove member');
      setMembers(members.filter(m => m.id !== memberId));
    } catch (err: any) {
      alert(err.message);
    }
  };

  return (
    <div className="flex flex-col h-screen font-sans antialiased bg-[#0f172a] text-slate-300 overflow-y-auto">
      {/* Header */}
      <header className="relative z-20 bg-slate-900/50 backdrop-blur-xl border-b border-slate-800/60 px-8 py-5 flex items-center justify-between shadow-2xl">
        <div className="flex items-center gap-4">
          <div className="w-12 h-12 bg-gradient-to-br from-indigo-500 to-purple-600 rounded-2xl flex items-center justify-center text-white shadow-lg shadow-indigo-500/20 ring-1 ring-white/10">
            <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2.5" d="M13 10V3L4 14h7v7l9-11h-7z" />
            </svg>
          </div>
          <div>
            <h1 className="text-xl font-black text-white tracking-tight leading-none uppercase">
              Reporting Agent <span className="text-slate-500 font-medium">/ {isAdmin ? 'Admin' : 'Profile'}</span>
            </h1>
            <p className="text-[10px] text-indigo-400 font-bold uppercase tracking-[0.2em] mt-1">
              {isAdmin ? 'Organization Management' : 'Profile Overview'}
            </p>
          </div>
        </div>
        <div className="flex items-center gap-4">
          <button onClick={() => navigate('/')} className="px-5 py-2.5 text-[10px] font-black text-indigo-400 hover:text-white bg-indigo-500/10 hover:bg-indigo-500 border border-indigo-500/30 rounded-xl uppercase tracking-widest transition-all">
            Back to Agent
          </button>
          <button onClick={async () => await supabase.auth.signOut()} className="px-5 py-2.5 text-[10px] font-black text-red-400 hover:text-white bg-red-500/10 hover:bg-red-500 border border-red-500/30 rounded-xl uppercase tracking-widest transition-all">
            Sign Out
          </button>
        </div>
      </header>

      <main className="p-8 max-w-6xl mx-auto w-full space-y-8">
        {error && <div className="p-4 bg-red-500/10 border border-red-500/20 text-red-400 rounded-lg">{error}</div>}

        {/* Organization Info */}
        {orgInfo && (
          <section className="bg-slate-900/40 border border-slate-800/50 rounded-2xl p-6 shadow-xl flex items-center justify-between">
            <div>
              <h2 className="text-sm font-bold text-slate-500 uppercase tracking-widest mb-1">Organization</h2>
              <p className="text-2xl font-black text-white tracking-tight">{orgInfo.name}</p>
            </div>
            <div className="text-right">
              <h2 className="text-sm font-bold text-slate-500 uppercase tracking-widest mb-2">Invite Code</h2>
              <div className="inline-flex items-center gap-3 bg-slate-800/50 border border-slate-700/50 px-4 py-2 rounded-lg">
                <code className="text-xl font-mono font-bold text-indigo-400 tracking-widest">{orgInfo.code}</code>
                <button onClick={() => { navigator.clipboard.writeText(orgInfo!.code); alert('Code copied!'); }} className="text-slate-400 hover:text-white transition-colors" title="Copy code">
                  <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M8 5H6a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2v-1M8 5a2 2 0 002 2h2a2 2 0 002-2M8 5a2 2 0 012-2h2a2 2 0 012 2m0 0h2a2 2 0 012 2v3m2 4H10m0 0l3-3m-3 3l3 3" />
                  </svg>
                </button>
              </div>
            </div>
          </section>
        )}

        {isAdmin ? (
          <>
            {/* Members Section */}
            <section className="bg-slate-900/40 border border-slate-800/50 rounded-2xl p-6 shadow-xl">
              <h2 className="text-lg font-bold text-white mb-4 uppercase tracking-widest">Organization Members</h2>
              {loading ? (
                <p className="text-slate-500 text-sm">Loading members…</p>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-left border-collapse">
                    <thead>
                      <tr className="border-b border-slate-700/50 text-xs uppercase tracking-wider text-slate-500">
                        <th className="pb-3 pr-4">Email</th>
                        <th className="pb-3 px-4">Role</th>
                        <th className="pb-3 px-4">Joined</th>
                        <th className="pb-3 pl-4 text-right">Actions</th>
                      </tr>
                    </thead>
                    <tbody>
                      {members.map(member => (
                        <tr key={member.id} className="border-b border-slate-800/50 hover:bg-slate-800/20 transition-colors">
                          <td className="py-4 pr-4 text-sm font-medium text-slate-300">{member.email}</td>
                          <td className="py-4 px-4">
                            <span className={`px-2 py-1 rounded text-xs font-bold uppercase tracking-wider ${member.role === 'admin' ? 'bg-indigo-500/20 text-indigo-400 border border-indigo-500/30' : 'bg-slate-800 text-slate-400 border border-slate-700'}`}>
                              {member.role}
                            </span>
                          </td>
                          <td className="py-4 px-4 text-xs text-slate-500">{new Date(member.created_at).toLocaleDateString()}</td>
                          <td className="py-4 pl-4 text-right space-x-2">
                            {member.id !== profile?.id && (
                              <>
                                <button onClick={() => handleUpdateRole(member.id, member.role === 'admin' ? 'member' : 'admin')} className="px-3 py-1 bg-slate-800 hover:bg-slate-700 text-xs font-bold rounded uppercase tracking-wider text-slate-300 transition-colors">
                                  Toggle Role
                                </button>
                                <button onClick={() => handleRemoveMember(member.id)} className="px-3 py-1 bg-red-500/10 hover:bg-red-500/20 text-red-400 text-xs font-bold border border-red-500/20 rounded uppercase tracking-wider transition-colors">
                                  Remove
                                </button>
                              </>
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </section>

            {/* ── Knowledge Base (RAG) Section ───────────────────────────── */}
            <section className="bg-slate-900/40 border border-slate-800/50 rounded-2xl p-6 shadow-xl">
              {/* Header */}
              <div className="flex items-center justify-between mb-2">
                <div>
                  <h2 className="text-lg font-bold text-white uppercase tracking-widest flex items-center gap-2">
                    Knowledge Base
                    <span className="px-2 py-0.5 bg-emerald-500/20 text-emerald-400 border border-emerald-500/30 rounded text-[9px] uppercase tracking-wider">RAG Active</span>
                  </h2>
                  <p className="text-sm text-slate-400 mt-1">
                    Upload organizational documents. They are chunked, embedded with Cohere, and used to ground every report your team generates.
                  </p>
                </div>
                <div className="text-right text-xs text-slate-500 hidden sm:block">
                  <p className="font-bold text-slate-400">{docs.length}</p>
                  <p>document{docs.length !== 1 ? 's' : ''}</p>
                </div>
              </div>

              <div className="mt-5 space-y-4">
                {/* Drop Zone */}
                <div
                  onDragOver={e => { e.preventDefault(); setDragOver(true); }}
                  onDragLeave={() => setDragOver(false)}
                  onDrop={onDrop}
                  onClick={() => uploadState !== 'uploading' && fileInputRef.current?.click()}
                  className={`relative border-2 border-dashed rounded-xl p-10 text-center cursor-pointer transition-all duration-200 flex flex-col items-center justify-center gap-3
                    ${dragOver ? 'border-indigo-500 bg-indigo-500/10 scale-[1.01]' : 'border-slate-700/60 hover:border-indigo-500/60 hover:bg-slate-800/30'}
                    ${uploadState === 'uploading' ? 'pointer-events-none opacity-70' : ''}
                  `}
                >
                  <input ref={fileInputRef} type="file" className="hidden" accept=".pdf,.docx,.txt,.md,.ipynb" onChange={onFileChange} />

                  {uploadState === 'uploading' ? (
                    <>
                      <div className="w-10 h-10 border-2 border-indigo-500/30 border-t-indigo-500 rounded-full animate-spin" />
                      <p className="text-sm font-semibold text-indigo-400">{uploadMsg}</p>
                      <p className="text-xs text-slate-500">Chunking & embedding — this may take a moment…</p>
                    </>
                  ) : uploadState === 'success' ? (
                    <>
                      <div className="w-10 h-10 rounded-full bg-emerald-500/20 flex items-center justify-center">
                        <svg className="w-5 h-5 text-emerald-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2.5" d="M5 13l4 4L19 7" />
                        </svg>
                      </div>
                      <p className="text-sm font-semibold text-emerald-400">{uploadMsg}</p>
                      <p className="text-xs text-slate-500">Click or drop another file to continue</p>
                    </>
                  ) : uploadState === 'error' ? (
                    <>
                      <div className="w-10 h-10 rounded-full bg-red-500/20 flex items-center justify-center">
                        <svg className="w-5 h-5 text-red-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M12 9v2m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                        </svg>
                      </div>
                      <p className="text-sm font-semibold text-red-400">{uploadMsg}</p>
                      <p className="text-xs text-slate-500">Click to try again</p>
                    </>
                  ) : (
                    <>
                      <div className="w-12 h-12 rounded-xl bg-slate-800 border border-slate-700 flex items-center justify-center">
                        <svg className="w-6 h-6 text-indigo-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12" />
                        </svg>
                      </div>
                      <div>
                        <p className="text-sm font-bold text-slate-300">
                          {dragOver ? 'Drop to upload' : 'Drag & drop or click to upload'}
                        </p>
                        <p className="text-xs text-slate-500 mt-1">PDF, DOCX, TXT, IPYNB — max 50 MB</p>
                      </div>
                    </>
                  )}
                </div>

                {/* Document List */}
                {docsLoading ? (
                  <div className="flex items-center gap-2 py-4 text-sm text-slate-500">
                    <div className="w-4 h-4 border border-slate-600 border-t-slate-400 rounded-full animate-spin" />
                    Loading documents…
                  </div>
                ) : docs.length === 0 ? (
                  <div className="py-6 text-center">
                    <p className="text-sm text-slate-600 font-medium">No documents uploaded yet.</p>
                    <p className="text-xs text-slate-700 mt-1">Upload your first document above to start grounding reports with organizational knowledge.</p>
                  </div>
                ) : (
                  <div className="rounded-xl border border-slate-800/60 overflow-hidden">
                    <table className="w-full text-left">
                      <thead>
                        <tr className="bg-slate-800/40 border-b border-slate-700/50 text-[10px] uppercase tracking-widest text-slate-500">
                          <th className="px-4 py-3">File</th>
                          <th className="px-4 py-3">Type</th>
                          <th className="px-4 py-3">Size</th>
                          <th className="px-4 py-3">Chunks</th>
                          <th className="px-4 py-3">Uploaded</th>
                          <th className="px-4 py-3 text-right">Actions</th>
                        </tr>
                      </thead>
                      <tbody>
                        {docs.map((doc, idx) => (
                          <tr
                            key={doc.id}
                            className={`border-b border-slate-800/40 transition-colors hover:bg-slate-800/20 ${idx === docs.length - 1 ? 'border-b-0' : ''}`}
                          >
                            <td className="px-4 py-3">
                              <p className="text-sm font-medium text-slate-300 truncate max-w-[200px]" title={doc.file_name}>
                                {doc.file_name}
                              </p>
                            </td>
                            <td className="px-4 py-3">
                              <FileTypeTag type={doc.file_type} />
                            </td>
                            <td className="px-4 py-3 text-xs text-slate-500">{formatBytes(doc.file_size)}</td>
                            <td className="px-4 py-3">
                              <span className="text-xs font-mono text-indigo-400 bg-indigo-500/10 border border-indigo-500/20 px-2 py-0.5 rounded">
                                {doc.chunk_count}
                              </span>
                            </td>
                            <td className="px-4 py-3 text-xs text-slate-500">
                              {new Date(doc.created_at).toLocaleDateString()}
                            </td>
                            <td className="px-4 py-3 text-right">
                              <button
                                onClick={() => handleDelete(doc.id, doc.file_name)}
                                disabled={deletingId === doc.id}
                                className="px-3 py-1 bg-red-500/10 hover:bg-red-500/20 text-red-400 text-[10px] font-bold border border-red-500/20 rounded uppercase tracking-wider transition-colors disabled:opacity-40"
                              >
                                {deletingId === doc.id ? '…' : 'Remove'}
                              </button>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
            </section>
          </>
        ) : (
          /* User Profile Section */
          <section className="bg-slate-900/40 border border-slate-800/50 rounded-2xl p-6 shadow-xl">
            <h2 className="text-lg font-bold text-white mb-6 uppercase tracking-widest">My Profile</h2>
            <div className="space-y-6">
              <div>
                <label className="text-xs font-bold text-slate-500 uppercase tracking-widest block mb-1">Email Address</label>
                <p className="text-slate-300 font-medium text-lg">{profile?.email}</p>
              </div>
              <div>
                <label className="text-xs font-bold text-slate-500 uppercase tracking-widest block mb-2">Role Status</label>
                <span className="px-3 py-1.5 rounded-lg text-sm font-bold uppercase tracking-wider bg-slate-800 text-slate-400 border border-slate-700 inline-block">
                  {profile?.role || 'Member'}
                </span>
              </div>
              <div className="pt-4 border-t border-slate-800/50">
                <p className="text-sm text-slate-500">
                  You are a regular member of this organization. Contact your administrator to request additional permissions or to manage other users.
                </p>
              </div>
            </div>
          </section>
        )}
      </main>
    </div>
  );
}
