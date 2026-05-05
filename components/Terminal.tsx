
import React, { useEffect, useState, useRef } from 'react';

export interface LogEntry {
  id: string;
  timestamp: string;
  type: 'info' | 'warn' | 'error' | 'success' | 'api' | 'db' | 'guardrail';
  message: string;
  payload?: any;
}

interface TerminalProps {
  isOpen: boolean;
  onClose: () => void;
  logger: { subscribe: (cb: (entry: LogEntry) => void) => () => void };
}

const Terminal: React.FC<TerminalProps> = ({ isOpen, onClose, logger }) => {
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const unsubscribe = logger.subscribe((entry) => {
      setLogs((prev) => [...prev, entry].slice(-100));
    });
    return unsubscribe;
  }, [logger]);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [logs]);

  if (!isOpen) return null;

  const getTypeStyle = (type: string) => {
    switch (type) {
      case 'api': return 'text-indigo-400';
      case 'success': return 'text-emerald-400';
      case 'error': return 'text-red-400';
      case 'warn': return 'text-amber-400';
      case 'db': return 'text-pink-400';
      default: return 'text-slate-400';
    }
  };

  return (
    <div className="fixed bottom-0 left-0 right-0 h-1/3 bg-[#0f172a] border-t border-slate-800 z-50 flex flex-col shadow-2xl animate-in slide-in-from-bottom duration-300">
      <div className="flex items-center justify-between px-6 py-2 bg-slate-900 border-b border-slate-800">
        <div className="flex items-center gap-3">
          <div className="flex gap-1.5">
            <div className="w-3 h-3 rounded-full bg-red-500/80"></div>
            <div className="w-3 h-3 rounded-full bg-amber-500/80"></div>
            <div className="w-3 h-3 rounded-full bg-emerald-500/80"></div>
          </div>
          <span className="text-[10px] font-black uppercase tracking-[0.2em] text-slate-500 ml-4">System Telemetry Log</span>
        </div>
        <div className="flex items-center gap-4">
          <button
            onClick={() => setLogs([])}
            className="text-[9px] font-black uppercase text-slate-500 hover:text-white transition-colors"
          >
            Clear
          </button>
          <button
            onClick={onClose}
            className="text-slate-500 hover:text-white"
          >
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M6 18L18 6M6 6l12 12" /></svg>
          </button>
        </div>
      </div>

      <div
        ref={scrollRef}
        className="flex-1 overflow-y-auto p-6 font-mono text-[11px] leading-relaxed selection:bg-indigo-500/30"
      >
        {logs.length === 0 ? (
          <div className="text-slate-600 italic">No activity recorded...</div>
        ) : (
          <div className="space-y-1">
            {logs.map((log) => (
              <div key={log.id} className="group">
                <span className="text-slate-600 mr-3">[{log.timestamp}]</span>
                <span className={`${getTypeStyle(log.type)} font-bold mr-3`}>[{log.type.toUpperCase()}]</span>
                <span className="text-slate-300">{log.message}</span>
                {log.payload && (
                  <details className="ml-8 mt-1 text-slate-500 cursor-pointer">
                    <summary className="hover:text-slate-400 transition-colors">View Payload</summary>
                    <pre className="mt-2 p-3 bg-black/40 rounded-lg overflow-x-auto text-[10px]">
                      {JSON.stringify(log.payload, null, 2)}
                    </pre>
                  </details>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
};

export default Terminal;
