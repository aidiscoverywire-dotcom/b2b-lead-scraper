import { createContext, useContext, useState } from 'react';
import { api, ENDPOINTS } from './api';

const AuthContext = createContext(null);
export const useAuth = () => useContext(AuthContext);

export function AuthProvider({ children }) {
  const [token, setToken] = useState(() => localStorage.getItem('ls_token'));

  const saveToken = (t) => {
    if (t) localStorage.setItem('ls_token', t);
    else    localStorage.removeItem('ls_token');
    setToken(t);
  };

  const login  = async (username, pw) => {
    const r = await api.post(ENDPOINTS.login, { email: username, password: pw });
    saveToken(r.data.access_token || r.data.token);
  };
  const logout = () => {
    saveToken(null);
    localStorage.removeItem('ls_wizard_done');
    localStorage.removeItem('ls_last_job');
  };

  return <AuthContext.Provider value={{ token, login, logout }}>{children}</AuthContext.Provider>;
}

function getResetTokenFromUrl() {
  try {
    return new URLSearchParams(window.location.search).get('reset_token');
  } catch { return null; }
}

export function AuthGate() {
  const { login }            = useAuth();
  const [username, setUsername] = useState('');
  const [pw, setPw]          = useState('');
  const [error, setError]    = useState('');
  const [busy, setBusy]      = useState(false);
  // 'login' | 'forgot' | 'reset'
  const [mode, setMode]      = useState(() => getResetTokenFromUrl() ? 'reset' : 'login');
  const [resetToken]         = useState(() => getResetTokenFromUrl());
  const [forgotEmail, setForgotEmail] = useState('');
  const [forgotMsg, setForgotMsg]     = useState(null);
  const [newPw, setNewPw]    = useState('');
  const [newPw2, setNewPw2]  = useState('');
  const [resetMsg, setResetMsg]       = useState(null);

  const submit = async (e) => {
    e.preventDefault();
    setError(''); setBusy(true);
    try {
      await login(username, pw);
    } catch (err) {
      setError(err.response?.data?.detail || err.response?.data?.message || 'Invalid username or password.');
    } finally { setBusy(false); }
  };

  const submitForgot = async (e) => {
    e.preventDefault();
    setForgotMsg(null); setBusy(true);
    try {
      const r = await api.post(ENDPOINTS.forgotPassword, { email: forgotEmail });
      if (r.data.email_sent) {
        setForgotMsg({ ok: true, text: 'Reset link sent! Check your inbox (and spam). The link expires in 30 minutes.' });
      } else {
        setForgotMsg({ ok: true, text: 'Email sending is not set up on this machine, so no email was sent. To reset your password, open a terminal in the software folder and run: python reset_password.py \u2014 then sign in with the new password.' });
      }
    } catch (err) {
      setForgotMsg({ ok: false, text: 'Could not process the request. Please try again.' });
    } finally { setBusy(false); }
  };

  const submitReset = async (e) => {
    e.preventDefault();
    setResetMsg(null);
    if (newPw.length < 4) { setResetMsg({ ok: false, text: 'New password must be at least 4 characters.' }); return; }
    if (newPw !== newPw2) { setResetMsg({ ok: false, text: 'Passwords do not match.' }); return; }
    setBusy(true);
    try {
      await api.post(ENDPOINTS.resetPassword, { token: resetToken, new_password: newPw });
      try {
        const url = new URL(window.location.href);
        url.searchParams.delete('reset_token');
        window.history.replaceState({}, '', url.toString());
      } catch {}
      setResetMsg({ ok: true, text: 'Password changed! You can now sign in with your new password.' });
      setMode('login');
    } catch (err) {
      setResetMsg({ ok: false, text: err.response?.data?.detail || 'Could not reset the password.' });
    } finally { setBusy(false); }
  };

  const cardStyle = { padding: 28 };
  const msgBox = (m) => m && (
    <div style={{ fontSize: 13, padding: '10px 12px', borderRadius: 8, marginBottom: 16,
      background: m.ok ? '#f0fdf4' : '#fff1f2',
      border: `1.5px solid ${m.ok ? '#86efac' : '#fca5a5'}`,
      color: m.ok ? '#166534' : '#9f1239' }}>
      {m.text}
    </div>
  );

  return (
    <div className="auth-bg">
      <div style={{ width:'100%', maxWidth:400, padding:'0 16px' }}>
        {/* Logo mark */}
        <div style={{ textAlign:'center', marginBottom:28 }}>
          <div style={{
            width:56, height:56, borderRadius:14, margin:'0 auto 12px',
            background:'linear-gradient(135deg,#6366f1,#8b5cf6)',
            display:'flex', alignItems:'center', justifyContent:'center',
            boxShadow:'0 4px 20px rgba(99,102,241,.5)',
          }}>
            <svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="2.2">
              <circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/>
            </svg>
          </div>
          <h1 style={{ margin:0, color:'white', fontSize:22, fontWeight:800, letterSpacing:'-.3px' }}>LeadScraper Pro</h1>
          <p style={{ margin:'6px 0 0', color:'rgba(255,255,255,.55)', fontSize:13 }}>
            {mode === 'reset' ? 'Set a new password' : mode === 'forgot' ? 'Reset your password' : 'Sign in to continue'}
          </p>
        </div>

        {/* Card */}
        <div className="card" style={cardStyle}>
          {mode === 'login' && (
            <form onSubmit={submit}>
              <div style={{ marginBottom:16 }}>
                <label style={{ display:'block', fontSize:12, fontWeight:600, color:'var(--text-2)', marginBottom:6 }}>Username</label>
                <input type="text" required value={username} onChange={e=>setUsername(e.target.value)}
                  className="input" placeholder="admin" autoCapitalize="none" autoCorrect="off" />
              </div>
              <div style={{ marginBottom:8 }}>
                <label style={{ display:'block', fontSize:12, fontWeight:600, color:'var(--text-2)', marginBottom:6 }}>Password</label>
                <input type="password" required value={pw} onChange={e=>setPw(e.target.value)}
                  className="input" placeholder="••••••••" />
              </div>
              <p style={{ margin:'0 0 16px', fontSize:12, color:'var(--text-3)' }}>
                Default login: <strong>admin</strong> / <strong>123</strong> — change it after your first sign-in in Settings → Security.
              </p>

              {error && (
                <div style={{ background:'#fff1f2', border:'1.5px solid #fca5a5', borderRadius:8, padding:'10px 12px', marginBottom:16, color:'#9f1239', fontSize:13 }}>
                  {error}
                </div>
              )}

              <button type="submit" className="btn-primary" disabled={busy} style={{ width:'100%', justifyContent:'center', height:42, fontSize:14 }}>
                {busy ? 'Please wait…' : 'Sign in'}
              </button>
              <div style={{ textAlign:'center', marginTop:14 }}>
                <button type="button" onClick={() => { setMode('forgot'); setForgotMsg(null); }}
                  style={{ background:'none', border:'none', color:'var(--text-3)', fontSize:13, cursor:'pointer', textDecoration:'underline' }}>
                  Forgot password?
                </button>
              </div>
            </form>
          )}

          {mode === 'forgot' && (
            <form onSubmit={submitForgot}>
              <p style={{ margin:'0 0 16px', fontSize:13, color:'var(--text-2)' }}>
                Enter your username/email. If email sending is set up, you will receive a reset link.
              </p>
              <div style={{ marginBottom:16 }}>
                <label style={{ display:'block', fontSize:12, fontWeight:600, color:'var(--text-2)', marginBottom:6 }}>Username / Email</label>
                <input type="text" required value={forgotEmail} onChange={e=>setForgotEmail(e.target.value)}
                  className="input" placeholder="admin" autoCapitalize="none" autoCorrect="off" />
              </div>
              {msgBox(forgotMsg)}
              <button type="submit" className="btn-primary" disabled={busy} style={{ width:'100%', justifyContent:'center', height:42, fontSize:14 }}>
                {busy ? 'Please wait…' : 'Send reset link'}
              </button>
              <div style={{ textAlign:'center', marginTop:14 }}>
                <button type="button" onClick={() => setMode('login')}
                  style={{ background:'none', border:'none', color:'var(--text-3)', fontSize:13, cursor:'pointer', textDecoration:'underline' }}>
                  ← Back to sign in
                </button>
              </div>
            </form>
          )}

          {mode === 'reset' && (
            <form onSubmit={submitReset}>
              <p style={{ margin:'0 0 16px', fontSize:13, color:'var(--text-2)' }}>
                Choose a new password for your account.
              </p>
              <div style={{ marginBottom:12 }}>
                <label style={{ display:'block', fontSize:12, fontWeight:600, color:'var(--text-2)', marginBottom:6 }}>New password</label>
                <input type="password" required value={newPw} onChange={e=>setNewPw(e.target.value)}
                  className="input" placeholder="••••••••" />
              </div>
              <div style={{ marginBottom:16 }}>
                <label style={{ display:'block', fontSize:12, fontWeight:600, color:'var(--text-2)', marginBottom:6 }}>Confirm new password</label>
                <input type="password" required value={newPw2} onChange={e=>setNewPw2(e.target.value)}
                  className="input" placeholder="••••••••" />
              </div>
              {msgBox(resetMsg)}
              <button type="submit" className="btn-primary" disabled={busy} style={{ width:'100%', justifyContent:'center', height:42, fontSize:14 }}>
                {busy ? 'Please wait…' : 'Set new password'}
              </button>
              <div style={{ textAlign:'center', marginTop:14 }}>
                <button type="button" onClick={() => setMode('login')}
                  style={{ background:'none', border:'none', color:'var(--text-3)', fontSize:13, cursor:'pointer', textDecoration:'underline' }}>
                  ← Back to sign in
                </button>
              </div>
            </form>
          )}
        </div>
      </div>
    </div>
  );
}
