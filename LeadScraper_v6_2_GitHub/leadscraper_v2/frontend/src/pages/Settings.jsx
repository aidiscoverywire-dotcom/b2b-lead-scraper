import { useEffect, useState } from 'react';
import { api, ENDPOINTS } from '../api';

const KEY_DEFS = [
  { id:'openai', keyName:'openai_key',      label:'OpenAI API Key',      icon:'🤖', hint:'Generates pitch lines and lead quality scores. Optional — you can skip it.', testEndpoint: ENDPOINTS.wizardTestOpenAI },
  { id:'apollo', keyName:'apollo_key',       label:'Apollo API Key',      icon:'🛰',  hint:'Company + decision-maker email enrichment. Free tier: ~75 reveals/mo. $49/mo plan for full volume. Optional.', testEndpoint: ENDPOINTS.wizardTestApollo },
  { id:'google', keyName:'google_maps_key',  label:'Google Maps API Key', icon:'🗺',  hint:'Business data via Places API (New). Enable "Places API (New)" in Google Cloud Console. Required.', testEndpoint: ENDPOINTS.wizardTestMaps },
];

export default function Settings() {
  const [saved, setSaved]     = useState({});
  const [values, setValues]   = useState({ openai:'', apollo:'', google:'' });
  const [results, setResults] = useState({});
  const [busy, setBusy]       = useState({});
  const [loaded, setLoaded]   = useState(false);

  const load = async () => {
    try { const r = await api.get(ENDPOINTS.settings); setSaved(r.data||{}); }
    catch { setSaved({}); }
    finally { setLoaded(true); }
  };
  useEffect(()=>{ load(); },[]);

  const maskedOf = (def) => (saved.keys && saved.keys[def.keyName]) || saved[def.id] || '';
  const setBusyFor = (id,v) => setBusy(p=>({...p,[id]:v}));
  const setResult  = (id,r) => setResults(p=>({...p,[id]:r}));

  const testKey = async (def) => {
    if (!values[def.id]) return;
    setBusyFor(def.id,'test');
    try {
      const r = await api.post(def.testEndpoint, { key:values[def.id] });
      setResult(def.id, { ok:true, message: r.data?.tier_hint || r.data?.message || 'Key works.' });
    } catch(err) {
      setResult(def.id, { ok:false, message: err.response?.data?.detail || err.response?.data?.message || 'Key test failed.' });
    } finally { setBusyFor(def.id,null); }
  };

  const saveKey = async (def) => {
    if (!values[def.id]) return;
    setBusyFor(def.id,'save');
    try {
      await api.put(ENDPOINTS.settings, { key_name:def.keyName, value:values[def.id] });
      setResult(def.id, { ok:true, message:'Saved securely.' });
      setValues(p=>({...p,[def.id]:''}));
      load();
    } catch(err) {
      setResult(def.id, { ok:false, message: err.response?.data?.detail || 'Save failed.' });
    } finally { setBusyFor(def.id,null); }
  };

  const googleConfigured = !!(saved.keys && saved.keys['google_maps_key']);
  // Google Maps is the only mandatory key — OpenAI/Apollo are optional (skippable).
  const setupComplete = googleConfigured;

  return (
    <div style={{ maxWidth:640, display:'flex', flexDirection:'column', gap:16 }}>

      {/* Setup Required Banner */}
      {loaded && !setupComplete && (
        <div style={{
          background:'linear-gradient(135deg,#6366f1,#8b5cf6)',
          borderRadius:12, padding:'18px 20px', color:'white',
        }}>
          <div style={{ fontWeight:700, fontSize:15, marginBottom:6 }}>⚡ Setup Required</div>
          <p style={{ margin:'0 0 10px', fontSize:13, opacity:.9, lineHeight:1.5 }}>
            You are on the <strong>Free Trial</strong> — up to <strong>5 leads</strong> without any API keys.
            Add your keys below to unlock full access and scrape hundreds of leads.
          </p>
          <div style={{ display:'flex', gap:8, flexWrap:'wrap' }}>
            {!googleConfigured && <span style={{ background:'rgba(255,255,255,.2)', borderRadius:6, padding:'3px 10px', fontSize:12, fontWeight:600 }}>✗ Google Maps key missing (required)</span>}
          </div>
        </div>
      )}

      {loaded && setupComplete && (
        <div style={{ background:'#f0fdf4', border:'1.5px solid #86efac', borderRadius:12, padding:'14px 18px', display:'flex', alignItems:'center', gap:10 }}>
          <span style={{ fontSize:20 }}>✅</span>
          <div style={{ fontSize:13, color:'#166534', fontWeight:600 }}>All keys configured — full access unlocked.</div>
        </div>
      )}

      <div className="card" style={{ padding:'20px 24px' }}>
        <h2 style={{ margin:'0 0 4px', fontSize:15, fontWeight:700, color:'var(--text-1)' }}>API Keys</h2>
        <p style={{ margin:'0 0 20px', fontSize:13, color:'var(--text-3)' }}>
          Keys are encrypted at rest. You pay Google, Apollo, and OpenAI directly.
        </p>

        {!loaded && (
          <div style={{ color:'var(--text-3)', fontSize:13 }}>Loading…</div>
        )}

        {KEY_DEFS.map((def, idx) => {
          const masked = maskedOf(def);
          const r = results[def.id];
          return (
            <div key={def.id} style={{ paddingTop: idx===0?0:20, marginTop: idx===0?0:20, borderTop: idx===0?'none':'1px solid var(--border)' }}>
              {/* Header */}
              <div style={{ display:'flex', alignItems:'center', justifyContent:'space-between', marginBottom:6 }}>
                <div style={{ display:'flex', alignItems:'center', gap:8 }}>
                  <span style={{ fontSize:18 }}>{def.icon}</span>
                  <span style={{ fontWeight:600, fontSize:14, color:'var(--text-1)' }}>{def.label}</span>
                </div>
                {masked
                  ? <span className="badge badge-green">● Configured</span>
                  : <span className="badge badge-gray">○ Not set</span>}
              </div>

              <p style={{ fontSize:12, color:'var(--text-3)', margin:'0 0 10px' }}>{def.hint}</p>

              {masked && (
                <div style={{ fontSize:11, fontFamily:'monospace', color:'var(--text-3)', background:'var(--surface-2)', border:'1px solid var(--border)', borderRadius:6, padding:'5px 10px', marginBottom:10 }}>
                  Current: {masked}
                </div>
              )}

              <div style={{ display:'flex', gap:8 }}>
                <input
                  type="password"
                  placeholder={masked ? 'Enter new key to replace' : 'Paste key here'}
                  value={values[def.id]}
                  onChange={e=>{ setValues(p=>({...p,[def.id]:e.target.value})); setResult(def.id,null); }}
                  className="input"
                  style={{ flex:1 }}
                />
                <button className="btn-ghost" onClick={()=>testKey(def)}
                  disabled={!values[def.id]||!!busy[def.id]}
                  style={{ height:38, padding:'0 14px', fontSize:13, flexShrink:0 }}>
                  {busy[def.id]==='test'?'Testing…':'Test'}
                </button>
                <button className="btn-primary" onClick={()=>saveKey(def)}
                  disabled={!values[def.id]||!!busy[def.id]}
                  style={{ height:38, padding:'0 14px', fontSize:13, flexShrink:0 }}>
                  {busy[def.id]==='save'?'Saving…':'Save'}
                </button>
              </div>

              {r && (
                <div style={{
                  marginTop:10, padding:'9px 12px', borderRadius:8, fontSize:13,
                  background: r.ok ? '#f0fdf4' : '#fff1f2',
                  border: `1.5px solid ${r.ok?'#86efac':'#fca5a5'}`,
                  color: r.ok ? '#166534' : '#9f1239',
                }}>
                  {r.ok ? '✓ ' : '✕ '}{r.message}
                </div>
              )}
            </div>
          );
        })}
      </div>

      <SecurityCard />
      <SmtpCard />

      {/* Data notice */}
      <div className="card" style={{ padding:'16px 20px', background:'#f0fdf4', borderColor:'#86efac' }}>
        <div style={{ display:'flex', gap:12, alignItems:'flex-start' }}>
          <span style={{ fontSize:20, flexShrink:0 }}>🔒</span>
          <div>
            <div style={{ fontWeight:600, fontSize:13, color:'#166534', marginBottom:4 }}>Data & Privacy</div>
            <p style={{ margin:0, fontSize:12, color:'#4b7c5b', lineHeight:1.6 }}>
              You are the data controller for your searches. Business data comes from the official Google Places API and (optionally) Apollo — no scraped data. API keys are AES-256 encrypted at rest.
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}

function SecurityCard() {
  const [current, setCurrent] = useState('');
  const [next, setNext]       = useState('');
  const [confirm, setConfirm] = useState('');
  const [busy, setBusy]       = useState(false);
  const [msg, setMsg]         = useState(null);

  const submit = async (e) => {
    e.preventDefault();
    setMsg(null);
    if (next.length < 4) { setMsg({ ok:false, text:'New password must be at least 4 characters.' }); return; }
    if (next !== confirm) { setMsg({ ok:false, text:'New password and confirmation do not match.' }); return; }
    setBusy(true);
    try {
      await api.put(ENDPOINTS.changePassword, { current_password: current, new_password: next });
      setMsg({ ok:true, text:'Password changed.' });
      setCurrent(''); setNext(''); setConfirm('');
    } catch (err) {
      setMsg({ ok:false, text: err.response?.data?.detail || 'Could not change password.' });
    } finally { setBusy(false); }
  };

  return (
    <div className="card" style={{ padding:'20px 24px' }}>
      <h2 style={{ margin:'0 0 4px', fontSize:15, fontWeight:700, color:'var(--text-1)' }}>🔐 Security</h2>
      <p style={{ margin:'0 0 16px', fontSize:13, color:'var(--text-3)' }}>
        Change the login username-and-password used for this software (default was <strong>admin</strong> / <strong>123</strong>).
      </p>
      <form onSubmit={submit} style={{ display:'flex', flexDirection:'column', gap:10, maxWidth:360 }}>
        <input type="password" className="input" placeholder="Current password" value={current} onChange={e=>setCurrent(e.target.value)} />
        <input type="password" className="input" placeholder="New password" value={next} onChange={e=>setNext(e.target.value)} />
        <input type="password" className="input" placeholder="Confirm new password" value={confirm} onChange={e=>setConfirm(e.target.value)} />
        {msg && (
          <div style={{ fontSize:13, padding:'8px 12px', borderRadius:8,
            background: msg.ok ? '#f0fdf4' : '#fff1f2', border:`1.5px solid ${msg.ok?'#86efac':'#fca5a5'}`, color: msg.ok?'#166534':'#9f1239' }}>
            {msg.text}
          </div>
        )}
        <button type="submit" className="btn-primary" disabled={busy || !current || !next}
          style={{ height:38, fontSize:13, alignSelf:'flex-start', padding:'0 16px' }}>
          {busy ? 'Saving…' : 'Change password'}
        </button>
      </form>
    </div>
  );
}

function SmtpCard() {
  const [form, setForm]     = useState({ host:'', port:587, username:'', password:'', from_email:'', from_name:'', use_tls:true });
  const [configured, setConfigured] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [busy, setBusy]     = useState(false);
  const [msg, setMsg]       = useState(null);
  const [testTo, setTestTo] = useState('');
  const [testMsg, setTestMsg] = useState(null);

  useEffect(() => {
    api.get(ENDPOINTS.smtpSettings).then(r => {
      setConfigured(!!r.data?.configured);
      if (r.data?.configured) setForm(p => ({ ...p, ...r.data, password:'' }));
    }).catch(()=>{}).finally(()=>setLoaded(true));
  }, []);

  const set = (k,v) => setForm(p => ({ ...p, [k]:v }));

  const save = async (e) => {
    e.preventDefault();
    setMsg(null); setBusy(true);
    try {
      await api.put(ENDPOINTS.smtpSettings, { ...form, port: Number(form.port) || 587 });
      setMsg({ ok:true, text:'SMTP settings saved.' });
      setConfigured(true);
    } catch (err) {
      setMsg({ ok:false, text: err.response?.data?.detail || 'Save failed.' });
    } finally { setBusy(false); }
  };

  const sendTest = async () => {
    if (!testTo) return;
    setTestMsg(null);
    try {
      const r = await api.post(ENDPOINTS.smtpTest, { to_email: testTo });
      setTestMsg({ ok: r.data.ok, text: r.data.message });
    } catch (err) {
      setTestMsg({ ok:false, text: err.response?.data?.detail || 'Test failed.' });
    }
  };

  return (
    <div className="card" style={{ padding:'20px 24px' }}>
      <h2 style={{ margin:'0 0 4px', fontSize:15, fontWeight:700, color:'var(--text-1)' }}>✉ Bulk Email (send from this software)</h2>
      <p style={{ margin:'0 0 16px', fontSize:13, color:'var(--text-3)' }}>
        Add your own SMTP account (Gmail, Outlook, Zoho, or a transactional provider) so you can email every
        collected lead at once from the Search page — no separate tool needed. Optional.
      </p>
      {!loaded ? <div style={{ fontSize:13, color:'var(--text-3)' }}>Loading…</div> : (
        <form onSubmit={save} style={{ display:'flex', flexDirection:'column', gap:10, maxWidth:420 }}>
          <div style={{ display:'flex', gap:10 }}>
            <input className="input" placeholder="smtp.gmail.com" style={{ flex:2 }} value={form.host} onChange={e=>set('host',e.target.value)} />
            <input className="input" placeholder="Port" style={{ flex:1 }} value={form.port} onChange={e=>set('port',e.target.value)} />
          </div>
          <input className="input" placeholder="SMTP username" value={form.username} onChange={e=>set('username',e.target.value)} />
          <input type="password" className="input" placeholder={configured ? 'Enter new password to replace' : 'SMTP password / app password'} value={form.password} onChange={e=>set('password',e.target.value)} />
          <input className="input" placeholder="From email — e.g. you@yourcompany.com" value={form.from_email} onChange={e=>set('from_email',e.target.value)} />
          <input className="input" placeholder="From name (optional)" value={form.from_name} onChange={e=>set('from_name',e.target.value)} />
          <label style={{ display:'flex', alignItems:'center', gap:8, fontSize:13, color:'var(--text-2)' }}>
            <input type="checkbox" checked={form.use_tls} onChange={e=>set('use_tls', e.target.checked)} style={{ width:16, height:16, accentColor:'var(--accent)' }} />
            Use STARTTLS (recommended, port 587)
          </label>
          {msg && (
            <div style={{ fontSize:13, padding:'8px 12px', borderRadius:8,
              background: msg.ok ? '#f0fdf4' : '#fff1f2', border:`1.5px solid ${msg.ok?'#86efac':'#fca5a5'}`, color: msg.ok?'#166534':'#9f1239' }}>
              {msg.text}
            </div>
          )}
          <button type="submit" className="btn-primary" disabled={busy || !form.host || !form.from_email}
            style={{ height:38, fontSize:13, alignSelf:'flex-start', padding:'0 16px' }}>
            {busy ? 'Saving…' : configured ? 'Update SMTP settings' : 'Save SMTP settings'}
          </button>
        </form>
      )}

      {configured && (
        <div style={{ marginTop:16, paddingTop:16, borderTop:'1px solid var(--border)', display:'flex', gap:8, alignItems:'center' }}>
          <input className="input" placeholder="Send a test email to…" value={testTo} onChange={e=>setTestTo(e.target.value)} style={{ flex:1 }} />
          <button className="btn-ghost" onClick={sendTest} disabled={!testTo} style={{ height:36, fontSize:13, padding:'0 14px' }}>Send test</button>
        </div>
      )}
      {testMsg && (
        <div style={{ marginTop:8, fontSize:13, padding:'8px 12px', borderRadius:8,
          background: testMsg.ok ? '#f0fdf4' : '#fff1f2', border:`1.5px solid ${testMsg.ok?'#86efac':'#fca5a5'}`, color: testMsg.ok?'#166534':'#9f1239' }}>
          {testMsg.text}
        </div>
      )}
    </div>
  );
}
