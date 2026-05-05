import React, { useState } from 'react';
import { useNavigate, Link } from 'react-router-dom';

export default function CreateOrgView() {
  const [orgName, setOrgName] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [createdOrg, setCreatedOrg] = useState<{name: string, code: string} | null>(null);
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setLoading(true);
    
    try {
      const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';
      const response = await fetch(`${API_URL}/api/auth/create-organization`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: orgName, email, password })
      });
      
      const data = await response.json();
      
      if (!response.ok) {
        throw new Error(data.detail || 'Organization creation failed');
      }
      
      setCreatedOrg(data.organization);
    } catch (err: any) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex flex-col h-screen font-sans antialiased bg-[#0f172a] text-slate-300 overflow-hidden items-center justify-center relative">
      {/* Dynamic Background */}
      <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_top_right,_var(--tw-gradient-stops))] from-indigo-900/20 via-[#0f172a] to-[#0f172a] pointer-events-none" />

      {/* Decorative Blob */}
      <div className="absolute top-1/4 left-1/4 w-96 h-96 bg-purple-500/10 rounded-full blur-3xl pointer-events-none"></div>
      <div className="absolute bottom-1/4 right-1/4 w-96 h-96 bg-indigo-500/10 rounded-full blur-3xl pointer-events-none"></div>

      <div className="relative z-10 w-full max-w-md p-10 bg-slate-900/50 backdrop-blur-xl border border-slate-800/60 rounded-[2.5rem] shadow-2xl animate-in zoom-in-95 duration-500">
        
        <div className="flex justify-center mb-8">
          <div className="w-16 h-16 bg-gradient-to-br from-purple-500 to-indigo-600 rounded-2xl flex items-center justify-center text-white shadow-lg shadow-purple-500/20 ring-1 ring-white/10">
            <svg className="w-8 h-8" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2.5" d="M19 21V5a2 2 0 00-2-2H7a2 2 0 00-2 2v16m14 0h2m-2 0h-5m-9 0H3m2 0h5M9 7h1m-1 4h1m4-4h1m-1 4h1m-5 10v-5a1 1 0 011-1h2a1 1 0 011 1v5m-4 0h4" /></svg>
          </div>
        </div>

        <div className="text-center mb-8">
          <h2 className="text-3xl font-black text-white tracking-tight leading-none uppercase">Create Org</h2>
          <p className="text-xs text-purple-400 font-bold uppercase tracking-[0.2em] mt-3 flex items-center justify-center gap-2">
            Establish Foundation
          </p>
        </div>

        {createdOrg ? (
          <div className="text-center animate-in zoom-in duration-300">
            <div className="mb-6 p-6 bg-emerald-500/10 border border-emerald-500/30 rounded-2xl">
              <h3 className="font-black text-lg text-emerald-400 uppercase tracking-widest mb-4">Organization Created!</h3>
              <p className="text-sm font-medium text-emerald-200/80 mb-3">Your unique organization code is:</p>
              <div className="bg-slate-950/50 px-6 py-4 text-3xl font-mono font-bold text-white border border-emerald-500/30 rounded-xl inline-block tracking-widest shadow-inner mb-4">
                {createdOrg.code}
              </div>
              <p className="text-[11px] text-emerald-400/80 uppercase tracking-wider font-bold">Save this code. Your team needs it to join.</p>
            </div>
            <Link to="/login" className="relative w-full inline-block py-5 rounded-2xl font-black text-[12px] uppercase tracking-[0.2em] overflow-hidden transition-all duration-300 bg-gradient-to-r from-emerald-600 to-indigo-600 text-white hover:shadow-[0_0_30px_rgba(16,185,129,0.3)] hover:scale-[1.02] active:scale-[0.98]">
              Continue to Login
            </Link>
          </div>
        ) : (
          <>
            {error && (
              <div className="mb-6 p-4 bg-red-500/10 border border-red-500/20 rounded-2xl text-center">
                 <p className="text-sm font-medium text-red-400">{error}</p>
              </div>
            )}
            
            <form onSubmit={handleSubmit} className="space-y-5">
              <div className="space-y-2">
                <label className="text-[10px] font-black text-slate-500 uppercase tracking-[0.2em] ml-2 block">Organization Name</label>
                <div className="relative group">
                  <input 
                    type="text" 
                    className="w-full px-5 py-4 bg-slate-950/50 border border-slate-700/50 rounded-2xl text-sm text-white focus:outline-none focus:border-purple-500 focus:ring-1 focus:ring-purple-500/50 transition-all placeholder:text-slate-600 shadow-inner"
                    value={orgName}
                    onChange={(e) => setOrgName(e.target.value)}
                    placeholder="e.g. Acme Corp"
                    required
                  />
                  <div className="absolute inset-0 rounded-2xl ring-1 ring-white/5 pointer-events-none group-hover:ring-white/10 transition-all"></div>
                </div>
              </div>
              
              <div className="space-y-2">
                <label className="text-[10px] font-black text-slate-500 uppercase tracking-[0.2em] ml-2 block">Admin Email</label>
                <div className="relative group">
                  <input 
                    type="email" 
                    className="w-full px-5 py-4 bg-slate-950/50 border border-slate-700/50 rounded-2xl text-sm text-white focus:outline-none focus:border-purple-500 focus:ring-1 focus:ring-purple-500/50 transition-all placeholder:text-slate-600 shadow-inner"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    placeholder="admin@acmecorp.com"
                    required
                  />
                  <div className="absolute inset-0 rounded-2xl ring-1 ring-white/5 pointer-events-none group-hover:ring-white/10 transition-all"></div>
                </div>
              </div>
              
              <div className="space-y-2">
                <label className="text-[10px] font-black text-slate-500 uppercase tracking-[0.2em] ml-2 block">Password</label>
                <div className="relative group">
                  <input 
                    type="password" 
                    className="w-full px-5 py-4 bg-slate-950/50 border border-slate-700/50 rounded-2xl text-sm text-white focus:outline-none focus:border-purple-500 focus:ring-1 focus:ring-purple-500/50 transition-all placeholder:text-slate-600 shadow-inner tracking-widest"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    placeholder="••••••••"
                    required
                  />
                  <div className="absolute inset-0 rounded-2xl ring-1 ring-white/5 pointer-events-none group-hover:ring-white/10 transition-all"></div>
                </div>
              </div>
              
              <div className="pt-4">
                <button 
                  type="submit" 
                  disabled={loading}
                  className={`relative w-full py-5 rounded-2xl font-black text-[12px] uppercase tracking-[0.2em] overflow-hidden transition-all duration-300 ${loading ? 'bg-slate-800/50 text-slate-500 cursor-not-allowed border border-slate-700/50' : 'bg-gradient-to-r from-purple-600 to-indigo-600 text-white hover:shadow-[0_0_30px_rgba(147,51,234,0.3)] hover:scale-[1.02] active:scale-[0.98]'}`}
                >
                  {loading ? (
                    <span className="flex items-center justify-center gap-3">
                      <svg className="animate-spin -ml-1 mr-3 h-4 w-4 text-slate-400" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24"><circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle><path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path></svg>
                      Creating...
                    </span>
                  ) : 'Create Organization'}
                  {!loading && <div className="absolute inset-0 bg-white/20 translate-y-full hover:translate-y-0 transition-transform duration-300"></div>}
                </button>
              </div>
            </form>
            
            <div className="mt-8 pt-6 border-t border-slate-800/50 text-center space-y-4">
              <p className="text-[11px] font-bold text-slate-500 uppercase tracking-widest">
                <Link to="/login" className="text-indigo-400 hover:text-indigo-300 transition-colors">Back to Login</Link>
              </p>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
