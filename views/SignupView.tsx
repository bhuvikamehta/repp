import React, { useState } from 'react';
import { useNavigate, Link } from 'react-router-dom';

export default function SignupView() {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [orgCode, setOrgCode] = useState('');
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');
  const [loading, setLoading] = useState(false);
  const navigate = useNavigate();

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setSuccess('');
    setLoading(true);
    
    try {
      const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';
      const response = await fetch(`${API_URL}/api/auth/signup`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, password, org_code: orgCode })
      });
      
      const data = await response.json();
      
      if (!response.ok) {
        throw new Error(data.detail || 'Signup failed');
      }
      
      setSuccess('Account successfully created! You can go log in now.');
      // Optional: Clear form
      setEmail('');
      setPassword('');
      setOrgCode('');
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
      <div className="absolute top-1/4 left-1/4 w-96 h-96 bg-emerald-500/10 rounded-full blur-3xl pointer-events-none"></div>
      <div className="absolute bottom-1/4 right-1/4 w-96 h-96 bg-purple-500/10 rounded-full blur-3xl pointer-events-none"></div>

      <div className="relative z-10 w-full max-w-md p-10 bg-slate-900/50 backdrop-blur-xl border border-slate-800/60 rounded-[2.5rem] shadow-2xl animate-in zoom-in-95 duration-500">
        
        <div className="flex justify-center mb-8">
          <div className="w-16 h-16 bg-gradient-to-br from-emerald-500 to-indigo-600 rounded-2xl flex items-center justify-center text-white shadow-lg shadow-emerald-500/20 ring-1 ring-white/10">
            <svg className="w-8 h-8" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2.5" d="M18 9v3m0 0v3m0-3h3m-3 0h-3m-2-5a4 4 0 11-8 0 4 4 0 018 0zM3 20a6 6 0 0112 0v1H3v-1z" /></svg>
          </div>
        </div>

        <div className="text-center mb-8">
          <h2 className="text-3xl font-black text-white tracking-tight leading-none uppercase">Sign Up</h2>
          <p className="text-xs text-emerald-400 font-bold uppercase tracking-[0.2em] mt-3 flex items-center justify-center gap-2">
            Create an Account
          </p>
        </div>

        {error && (
          <div className="mb-6 p-4 bg-red-500/10 border border-red-500/20 rounded-2xl text-center">
             <p className="text-sm font-medium text-red-400">{error}</p>
          </div>
        )}

        {success && (
          <div className="mb-6 p-4 bg-emerald-500/10 border border-emerald-500/20 rounded-2xl text-center">
             <p className="text-sm font-medium text-emerald-400">{success}</p>
             <Link to="/login" className="inline-block mt-3 px-4 py-2 bg-emerald-500/20 text-emerald-300 rounded-lg text-xs font-bold uppercase tracking-widest hover:bg-emerald-500/30 transition-colors">Go to Login</Link>
          </div>
        )}

        <form onSubmit={handleSubmit} className="space-y-5">
          <div className="space-y-2">
            <label className="text-[10px] font-black text-slate-500 uppercase tracking-[0.2em] ml-2 block">Organization Code</label>
            <div className="relative group">
              <input 
                type="text" 
                className="w-full px-5 py-4 bg-slate-950/50 border border-slate-700/50 rounded-2xl text-sm text-white focus:outline-none focus:border-emerald-500 focus:ring-1 focus:ring-emerald-500/50 transition-all placeholder:text-slate-600 shadow-inner uppercase"
                placeholder="e.g. A1B2C3D4"
                value={orgCode}
                onChange={(e) => setOrgCode(e.target.value)}
                required
              />
              <div className="absolute inset-0 rounded-2xl ring-1 ring-white/5 pointer-events-none group-hover:ring-white/10 transition-all"></div>
            </div>
            <p className="text-[10px] text-slate-500 ml-2">Ask your administrator for your organization's unique code.</p>
          </div>

          <div className="space-y-2">
            <label className="text-[10px] font-black text-slate-500 uppercase tracking-[0.2em] ml-2 block">Email</label>
            <div className="relative group">
              <input 
                type="email" 
                className="w-full px-5 py-4 bg-slate-950/50 border border-slate-700/50 rounded-2xl text-sm text-white focus:outline-none focus:border-emerald-500 focus:ring-1 focus:ring-emerald-500/50 transition-all placeholder:text-slate-600 shadow-inner"
                placeholder="agent@reporting-agent.com"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
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
                className="w-full px-5 py-4 bg-slate-950/50 border border-slate-700/50 rounded-2xl text-sm text-white focus:outline-none focus:border-emerald-500 focus:ring-1 focus:ring-emerald-500/50 transition-all placeholder:text-slate-600 shadow-inner tracking-widest"
                placeholder="••••••••"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
              />
              <div className="absolute inset-0 rounded-2xl ring-1 ring-white/5 pointer-events-none group-hover:ring-white/10 transition-all"></div>
            </div>
          </div>

          <div className="pt-4">
            <button 
              type="submit" 
              disabled={loading}
              className={`relative w-full py-5 rounded-2xl font-black text-[12px] uppercase tracking-[0.2em] overflow-hidden transition-all duration-300 ${loading ? 'bg-slate-800/50 text-slate-500 cursor-not-allowed border border-slate-700/50' : 'bg-gradient-to-r from-emerald-600 to-indigo-600 text-white hover:shadow-[0_0_30px_rgba(16,185,129,0.3)] hover:scale-[1.02] active:scale-[0.98]'}`}
            >
              {loading ? (
                <span className="flex items-center justify-center gap-3">
                  <svg className="animate-spin -ml-1 mr-3 h-4 w-4 text-slate-400" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24"><circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle><path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path></svg>
                  Signing up...
                </span>
              ) : 'Sign Up'}
              {!loading && <div className="absolute inset-0 bg-white/20 translate-y-full hover:translate-y-0 transition-transform duration-300"></div>}
            </button>
          </div>
        </form>

        <div className="mt-8 pt-6 border-t border-slate-800/50 text-center space-y-4">
          <p className="text-[11px] font-bold text-slate-500 uppercase tracking-widest">
            Already have an account? <Link to="/login" className="text-indigo-400 hover:text-indigo-300 transition-colors">Log In</Link>
          </p>
        </div>
      </div>
    </div>
  );
}
