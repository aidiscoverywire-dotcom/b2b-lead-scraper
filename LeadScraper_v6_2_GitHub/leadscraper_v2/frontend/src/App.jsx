import { useState, useEffect } from 'react';
import { AuthProvider, AuthGate, useAuth } from './auth';
import { getMeta } from './api';
import Search from './pages/Search';
import Settings from './pages/Settings';

/* ── Icons (inline SVG, no external dep) ───────────────────────── */
const Icon = {
  search: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/>
    </svg>
  ),
  settings: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="12" r="3"/>
      <path d="M19.07 4.93A10 10 0 1 0 4.93 19.07 10 10 0 0 0 19.07 4.93z"/>
    </svg>
  ),
  logout: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><polyline points="16 17 21 12 16 7"/><line x1="21" y1="12" x2="9" y2="12"/>
    </svg>
  ),
};

function Shell() {
  const { logout } = useAuth();
  const [tab, setTab] = useState('search');
  const [appVersion, setAppVersion] = useState('');

  useEffect(() => {
    const handler = () => setTab('settings');
    window.addEventListener('ls:goto-settings', handler);
    getMeta().then(m => m && m.version && setAppVersion(' v' + m.version)).catch(() => {});
    return () => window.removeEventListener('ls:goto-settings', handler);
  }, []);

  return (
    <div className="app-shell">
      {/* ── Sidebar ── */}
      <aside className="sidebar">
        {/* Logo */}
        <div style={{ padding:'18px 16px 14px', borderBottom:'1.5px solid var(--border)' }}>
          <div style={{ display:'flex', alignItems:'center', gap:10 }}>
            <div style={{
              width:36, height:36, borderRadius:9,
              background:'linear-gradient(135deg,#6366f1,#8b5cf6)',
              display:'flex', alignItems:'center', justifyContent:'center',
              boxShadow:'0 2px 8px rgba(99,102,241,.4)',
              flexShrink:0,
            }}>
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="2.2">
                <circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/>
              </svg>
            </div>
            <div>
              <div style={{ fontWeight:700, fontSize:13.5, color:'var(--text-1)', lineHeight:1.2 }}>LeadScraper</div>
              <div style={{ fontSize:11, color:'var(--text-3)', fontWeight:500 }}>B2B AI Platform</div>
            </div>
          </div>
        </div>

        {/* Nav */}
        <nav style={{ padding:'12px 0', flex:1 }}>
          <div style={{ fontSize:10, fontWeight:700, color:'var(--text-3)', textTransform:'uppercase', letterSpacing:'.08em', padding:'0 16px 6px' }}>
            Navigation
          </div>
          <button className={`nav-item${tab==='search'?' active':''}`} onClick={()=>setTab('search')}>
            {Icon.search}
            Lead Search
          </button>
          <button className={`nav-item${tab==='settings'?' active':''}`} onClick={()=>setTab('settings')}>
            {Icon.settings}
            Settings
          </button>
        </nav>

        {/* Bottom — user / logout */}
        <div style={{ padding:'12px', borderTop:'1.5px solid var(--border)' }}>
          <button className="nav-item" onClick={logout} style={{ color:'var(--red)', width:'100%' }}>
            {Icon.logout}
            Sign out
          </button>
          <div style={{ fontSize:10, color:'var(--text-3)', textAlign:'center', marginTop:8 }}>
            v1.6.0 · LeadScraper Pro
          </div>
        </div>
      </aside>

      {/* ── Main area ── */}
      <div className="main-area">
        {/* Topbar */}
        <div className="topbar">
          <div style={{ fontWeight:600, fontSize:14, color:'var(--text-1)' }}>
            {tab === 'search' ? '🔍 Lead Search' : '⚙️ Settings'}
          </div>
          <div style={{ flex:1 }} />
          <div style={{ fontSize:12, color:'var(--text-3)' }}>
            B2B AI Lead Scraper{appVersion}
          </div>
        </div>

        {/* Page */}
        <div className="page-body">
          {tab === 'search' ? <Search /> : <Settings />}
        </div>
      </div>
    </div>
  );
}

export default function App() {
  return (
    <AuthProvider>
      <AuthGateWrapper />
    </AuthProvider>
  );
}

function AuthGateWrapper() {
  const { token } = useAuth();
  if (!token) return <AuthGate />;
  return <Shell />;
}
