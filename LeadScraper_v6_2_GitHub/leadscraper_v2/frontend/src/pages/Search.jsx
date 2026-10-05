import { useEffect, useRef, useState } from 'react';
import { api, ENDPOINTS, openJobStream, downloadExport } from '../api';
import LeadsTable from '../components/LeadsTable';
import ProgressBar from '../components/ProgressBar';

export default function Search() {
  const [industry, setIndustry] = useState('');
  const [location, setLocation] = useState('');
  const [maxLeads, setMaxLeads] = useState(200);
  const [filters, setFilters]   = useState({ minRating:'', minReviews:'', companySize:'', emailAvailable:false });
  const [apolloOn, setApolloOn] = useState(false);
  const [needsGoogleKey, setNeedsGoogleKey] = useState(false);

  const [jobId, setJobId]       = useState(null);
  const [leads, setLeads]       = useState([]);
  const [progress, setProgress] = useState({ status:'idle', leads:0, requested:0 });
  const [starting, setStarting] = useState(false);
  const [startError, setStartError] = useState('');
  const [notice, setNotice]     = useState('');
  const [exporting, setExporting] = useState(null); // 'csv'|'xlsx'|null
  const [resumeInfo, setResumeInfo] = useState(null);

  // --- Bulk email (send one email to every collected lead at once) ---------
  const [showEmailPanel, setShowEmailPanel] = useState(false);
  const [emailSubject, setEmailSubject]     = useState('');
  const [emailBody, setEmailBody]           = useState('');
  const [onlyValidEmail, setOnlyValidEmail] = useState(true);
  const [eligibleCount, setEligibleCount]   = useState(null);
  const [campaign, setCampaign]             = useState(null); // {status,total,sent_count,failed_count}
  const [emailSending, setEmailSending]     = useState(false);
  const [emailError, setEmailError]         = useState('');
  const campaignPollRef = useRef(null);

  // Clear the campaign poller on unmount so a stale interval can't keep
  // hitting the API (or setState on an unmounted component) after the user
  // navigates away mid-send.
  useEffect(() => {
    return () => {
      if (campaignPollRef.current) clearInterval(campaignPollRef.current);
    };
  }, []);

  useEffect(() => {
    if (!showEmailPanel || !jobId) return;
    api.get(ENDPOINTS.emailEligibleCount(jobId), { params: { only_valid_email: onlyValidEmail } })
      .then(r => setEligibleCount(r.data?.eligible ?? 0))
      .catch(() => setEligibleCount(null));
  }, [showEmailPanel, jobId, onlyValidEmail]);

  const pollCampaign = (campaignId) => {
    if (campaignPollRef.current) clearInterval(campaignPollRef.current);
    campaignPollRef.current = setInterval(async () => {
      try {
        const r = await api.get(ENDPOINTS.campaign(campaignId));
        setCampaign(r.data);
        if (r.data.status === 'completed' || r.data.status === 'failed') {
          clearInterval(campaignPollRef.current);
        }
      } catch { clearInterval(campaignPollRef.current); }
    }, 2000);
  };

  const sendBulkEmail = async () => {
    setEmailError(''); setEmailSending(true);
    try {
      const r = await api.post(ENDPOINTS.bulkEmail(jobId), {
        subject: emailSubject, body_html: emailBody, only_valid_email: onlyValidEmail,
      });
      setCampaign({ status: 'pending', total: r.data.total, sent_count: 0, failed_count: 0 });
      pollCampaign(r.data.campaign_id);
    } catch (err) {
      setEmailError(err.response?.data?.detail || 'Could not start sending — check SMTP settings.');
    } finally { setEmailSending(false); }
  };

  const esRef   = useRef(null);
  const seenRef = useRef(new Set());
  const doneRef = useRef(false);
  const sf = (k,v) => setFilters(p => ({ ...p, [k]:v }));

  useEffect(() => {
    api.get(ENDPOINTS.settings).then(r => {
      setApolloOn(Boolean(r.data?.keys?.apollo_key));
      const keys = r.data?.keys || {};
      // Google Places is the only mandatory key — OpenAI/Apollo are optional.
      // Without it there is no real business data to collect (we never
      // fabricate leads), so search stays disabled until it is added.
      setNeedsGoogleKey(!keys.google_maps_key);
    }).catch(()=>{});
  }, []);

  const connectStream = (id) => {
    if (esRef.current) esRef.current.close();
    const es = openJobStream(id, {
      lead: (msg) => {
        const l = msg.lead || msg || {};
        const pid = l.place_id || l.id;
        if (pid && seenRef.current.has(pid)) return;
        if (pid) seenRef.current.add(pid);
        setLeads(p => [...p, l]);
      },
      progress: (msg) => setProgress({
        status: msg.status || 'running',
        leads:  msg.found ?? 0, requested: msg.requested ?? 0,
        searches: msg.sub_queries_run ?? 0, details: msg.detail_calls ?? 0,
        apolloCredits: msg.apollo_credits_used ?? msg.apolloCredits ?? 0,
      }),
      done: (msg) => {
        doneRef.current = true;
        setProgress(p => ({ ...p, status:'done', leads: msg.found ?? p.leads, requested: msg.requested ?? p.requested, searches: msg.sub_queries_run ?? p.searches ?? 0, details: msg.detail_calls ?? p.details ?? 0, apolloCredits: msg.apollo_credits_used ?? p.apolloCredits ?? 0 }));
        const n = msg.found ?? 0, m = msg.requested ?? 0;
        if (m > 0 && n < m) setNotice(`Found ${n} of ${m} requested — the area has fewer matching businesses. No filler leads added.`);
        else setNotice('');
        localStorage.removeItem('ls_last_job');
        if (esRef.current) esRef.current.close();
      },
      error: (msg) => {
        if (doneRef.current) return;
        setProgress(p => ({ ...p, status:'error' }));
        setNotice(msg.message || 'Stream error.');
      },
    });
    esRef.current = es;
  };

  useEffect(() => () => { if (esRef.current) esRef.current.close(); }, []);

  useEffect(() => {
    const last = localStorage.getItem('ls_last_job');
    if (!last) return;
    api.get(ENDPOINTS.job(last)).then(r => {
      if (r.data?.status === 'running') setResumeInfo({ jobId:last });
      else localStorage.removeItem('ls_last_job');
    }).catch(() => localStorage.removeItem('ls_last_job'));
  }, []);

  const resumeLast = () => {
    if (!resumeInfo) return;
    setJobId(resumeInfo.jobId); seenRef.current = new Set(); doneRef.current = false;
    setLeads([]); setNotice(''); connectStream(resumeInfo.jobId); setResumeInfo(null);
  };

  const startSearch = async () => {
    if (!industry.trim() || !location.trim()) { setStartError('Please enter industry and location.'); return; }
    if (needsGoogleKey) { setStartError('Add your Google Places API key in Settings → API Keys first.'); return; }
    setStartError(''); setNotice(''); setStarting(true);
    const effectiveMaxLeads = Math.min(1000, Math.max(1, Number(maxLeads) || 50));
    setMaxLeads(String(effectiveMaxLeads));
    try {
      const r = await api.post(ENDPOINTS.searchStart, {
        industry: industry.trim(), location: location.trim(),
        max_leads: effectiveMaxLeads,
        filters: {
          min_rating:      filters.minRating  === '' ? null : Number(filters.minRating),
          min_reviews:     filters.minReviews === '' ? null : Number(filters.minReviews),
          min_company_size:filters.companySize || null,
          email_required:  filters.emailAvailable || null,
        },
      });
      const id = r.data.job_id || r.data.jobId || r.data.id;
      setJobId(id); seenRef.current = new Set(); doneRef.current = false; setLeads([]);
      setProgress({ status:'running', leads:0, requested:effectiveMaxLeads, searches:0, details:0, apolloCredits:0 });
      localStorage.setItem('ls_last_job', id);
      connectStream(id);
    } catch (err) {
      setStartError(err.response?.data?.detail || err.response?.data?.message || 'Could not start search.');
    } finally { setStarting(false); }
  };

  const doExport = async (fmt) => {
    if (!jobId) return;
    setExporting(fmt);
    try {
      const result = await downloadExport(jobId, fmt);
      // Desktop app: server saved the file to ~/Downloads and returned the path.
      if (result && result.path) setNotice(`Saved ${result.leads} leads to ${result.path}`);
    }
    catch (err) { setNotice('Export failed: ' + (err.response?.data?.detail || err.message)); }
    finally { setExporting(null); }
  };

  const isRunning = progress.status === 'running';

  return (
    <div style={{ display:'flex', flexDirection:'column', gap:14 }}>

      {/* ── Google key required banner ── */}
      {needsGoogleKey && (
        <div style={{
          display:'flex', alignItems:'center', justifyContent:'space-between', flexWrap:'wrap', gap:10,
          background:'linear-gradient(135deg,#f59e0b,#ef4444)',
          borderRadius:10, padding:'12px 16px', color:'white',
        }}>
          <div style={{ display:'flex', alignItems:'center', gap:10 }}>
            <span style={{ fontSize:18 }}>🔑</span>
            <div>
              <div style={{ fontWeight:700, fontSize:13 }}>Google Places API key required</div>
              <div style={{ fontSize:12, opacity:.9, marginTop:2 }}>Search needs real business data — add your key in Settings to unlock lead scraping.</div>
            </div>
          </div>
          <button
            onClick={() => {
              // Trigger Settings tab — we dispatch a custom event since tab state is in Shell
              window.dispatchEvent(new CustomEvent('ls:goto-settings'));
            }}
            style={{
              background:'rgba(255,255,255,.2)', border:'1.5px solid rgba(255,255,255,.4)',
              color:'white', borderRadius:8, padding:'6px 14px', fontSize:12, fontWeight:600,
              cursor:'pointer', whiteSpace:'nowrap',
            }}>
            ⚙ Add API Key
          </button>
        </div>
      )}

      {/* ── Search panel ── */}
      <div className="card" style={{ padding:'18px 20px' }}>
        <div style={{ display:'flex', gap:12, flexWrap:'wrap', alignItems:'flex-end' }}>
          {/* Industry */}
          <div style={{ flex:'1 1 160px', minWidth:140 }}>
            <label style={{ display:'block', fontSize:11, fontWeight:700, color:'var(--text-3)', textTransform:'uppercase', letterSpacing:'.05em', marginBottom:5 }}>
              Industry
            </label>
            <input className="input" value={industry} onChange={e=>setIndustry(e.target.value)}
              placeholder="e.g. Dentists" onKeyDown={e=>e.key==='Enter'&&startSearch()} />
          </div>
          {/* Location */}
          <div style={{ flex:'1 1 160px', minWidth:140 }}>
            <label style={{ display:'block', fontSize:11, fontWeight:700, color:'var(--text-3)', textTransform:'uppercase', letterSpacing:'.05em', marginBottom:5 }}>
              Location
            </label>
            <input className="input" value={location} onChange={e=>setLocation(e.target.value)}
              placeholder="e.g. Austin, TX" onKeyDown={e=>e.key==='Enter'&&startSearch()} />
          </div>
          {/* Max leads */}
          <div style={{ flex:'0 0 120px' }}>
            <label style={{ display:'block', fontSize:11, fontWeight:700, color:'var(--text-3)', textTransform:'uppercase', letterSpacing:'.05em', marginBottom:5 }}>
              Max leads
            </label>
            <input className="input" type="number" min={1} max={1000} value={maxLeads}
              onChange={e=>setMaxLeads(e.target.value)} title="1 – 1000" />
            <div style={{ fontSize:10, color:'var(--text-3)', marginTop:3 }}>1 – 1000</div>
          </div>
          {/* Apollo status */}
          <div style={{ flex:'0 0 130px' }}>
            <label style={{ display:'block', fontSize:11, fontWeight:700, color:'var(--text-3)', textTransform:'uppercase', letterSpacing:'.05em', marginBottom:5 }}>
              Enrichment
            </label>
            <div style={{ display:'flex', alignItems:'center', gap:7, height:38 }}>
              <span style={{ width:8, height:8, borderRadius:'50%', background: apolloOn?'var(--green)':'#cbd5e1', flexShrink:0 }} />
              <span style={{ fontSize:13, color: apolloOn?'var(--green)':'var(--text-3)', fontWeight:600 }}>
                {apolloOn ? 'Apollo ON' : 'Apollo OFF'}
              </span>
            </div>
          </div>
          {/* Start button */}
          <div style={{ alignSelf:'flex-end' }}>
            <button className="btn-primary" onClick={startSearch}
              disabled={starting || isRunning || needsGoogleKey}
              title={needsGoogleKey ? 'Add your Google Places API key in Settings first' : ''}
              style={{ height:38, paddingLeft:20, paddingRight:20, fontSize:14, fontWeight:700 }}>
              {starting ? 'Starting…' : isRunning ? (
                <><span style={{ display:'inline-block', animation:'spin 1s linear infinite', marginRight:6 }}>⟳</span>Searching…</>
              ) : (
                <><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" style={{marginRight:6}}><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>Start Search</>
              )}
            </button>
          </div>
        </div>

        {/* Filters */}
        <div style={{ display:'flex', gap:12, flexWrap:'wrap', marginTop:14, paddingTop:14, borderTop:'1px solid var(--border)', alignItems:'flex-end' }}>
          <div style={{ flex:'0 0 110px' }}>
            <label style={{ display:'block', fontSize:11, fontWeight:600, color:'var(--text-3)', marginBottom:5 }}>Min Rating</label>
            <select className="input" value={filters.minRating} onChange={e=>sf('minRating',e.target.value)}>
              <option value="">Any</option>
              {[3,3.5,4,4.5].map(r=><option key={r} value={r}>{r}+</option>)}
            </select>
          </div>
          <div style={{ flex:'0 0 110px' }}>
            <label style={{ display:'block', fontSize:11, fontWeight:600, color:'var(--text-3)', marginBottom:5 }}>Min Reviews</label>
            <input type="number" min="0" className="input" value={filters.minReviews} onChange={e=>sf('minReviews',e.target.value)} placeholder="Any" />
          </div>
          <div style={{ flex:'0 0 130px' }}>
            <label style={{ display:'block', fontSize:11, fontWeight:600, color:'var(--text-3)', marginBottom:5 }}>Company Size</label>
            <select className="input" value={filters.companySize} onChange={e=>sf('companySize',e.target.value)}>
              <option value="">Any</option>
              <option value="1-10">1–10</option>
              <option value="11-50">11–50</option>
              <option value="51-200">51–200</option>
              <option value="201-500">201–500</option>
              <option value="501+">501+</option>
            </select>
          </div>
          <div style={{ display:'flex', alignItems:'center', height:38, gap:8 }}>
            <input type="checkbox" id="hasEmail" checked={filters.emailAvailable} onChange={e=>sf('emailAvailable',e.target.checked)}
              style={{ width:16, height:16, accentColor:'var(--accent)', cursor:'pointer' }} />
            <label htmlFor="hasEmail" style={{ fontSize:13, color:'var(--text-2)', cursor:'pointer', userSelect:'none' }}>
              Has email
              {!apolloOn && <span style={{ fontSize:11, color:'var(--text-3)', marginLeft:4 }}>(needs Apollo key)</span>}
            </label>
          </div>
          <div style={{ flex:1 }} />
          {/* Export buttons — right-aligned in filter row */}
          <div style={{ display:'flex', gap:8, alignItems:'center' }}>
            <span style={{ fontSize:11, fontWeight:700, color:'var(--text-3)', textTransform:'uppercase', letterSpacing:'.05em' }}>Export</span>
            <button className="btn-ghost" onClick={()=>doExport('csv')} disabled={!jobId||!!exporting}
              style={{ height:34, fontSize:12, padding:'0 12px' }}>
              {exporting==='csv'?'Exporting…':'⬇ CSV'}
            </button>
            <button className="btn-ghost" onClick={()=>doExport('xlsx')} disabled={!jobId||!!exporting}
              style={{ height:34, fontSize:12, padding:'0 12px' }}>
              {exporting==='xlsx'?'Exporting…':'⬇ Excel'}
            </button>
            <button className="btn-primary" onClick={()=>setShowEmailPanel(v=>!v)} disabled={!jobId || leads.length===0}
              style={{ height:34, fontSize:12, padding:'0 14px' }}>
              ✉ Send Email to Leads
            </button>
          </div>
        </div>

        {startError && (
          <div style={{ marginTop:12, padding:'9px 12px', background:'#fff1f2', border:'1.5px solid #fca5a5', borderRadius:8, color:'#9f1239', fontSize:13 }}>
            {startError}
          </div>
        )}
      </div>

      {/* Resume banner */}
      {resumeInfo && (
        <div style={{ display:'flex', alignItems:'center', gap:12, padding:'12px 16px',
          background:'#fffbeb', border:'1.5px solid #fcd34d', borderRadius:10 }}>
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#d97706" strokeWidth="2">
            <circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/>
          </svg>
          <span style={{ fontSize:13, color:'#92400e', flex:1 }}>A previous search was interrupted — reconnect to continue receiving leads.</span>
          <button className="btn-ghost" onClick={resumeLast} style={{ height:32, fontSize:12, padding:'0 12px' }}>Reconnect</button>
          <button onClick={()=>{ setResumeInfo(null); localStorage.removeItem('ls_last_job'); }}
            style={{ background:'none', border:'none', cursor:'pointer', color:'#b45309', fontSize:12 }}>Dismiss</button>
        </div>
      )}

      {/* Progress */}
      <ProgressBar progress={progress} />

      {/* Notice */}
      {notice && (
        <div style={{
          padding:'10px 14px', borderRadius:10, fontSize:13,
          background: progress.status==='error' ? '#fff1f2' : '#f0fdf4',
          border: `1.5px solid ${progress.status==='error' ? '#fca5a5' : '#86efac'}`,
          color: progress.status==='error' ? '#9f1239' : '#166534',
        }}>
          {notice}
        </div>
      )}

      {/* Bulk email panel */}
      {showEmailPanel && (
        <div className="card" style={{ padding:'18px 20px', display:'flex', flexDirection:'column', gap:12 }}>
          <div style={{ display:'flex', justifyContent:'space-between', alignItems:'center' }}>
            <h3 style={{ margin:0, fontSize:14, fontWeight:700, color:'var(--text-1)' }}>Send one email to every collected lead</h3>
            <button onClick={()=>setShowEmailPanel(false)} style={{ background:'none', border:'none', cursor:'pointer', color:'var(--text-3)', fontSize:13 }}>✕ Close</button>
          </div>
          <p style={{ margin:0, fontSize:12, color:'var(--text-3)' }}>
            Sends over your own SMTP account (set up under Settings → Bulk Email). Use {'{{name}}'}, {'{{company}}'}, {'{{title}}'} to personalize each email.
          </p>

          <div style={{ display:'flex', alignItems:'center', gap:8 }}>
            <input type="checkbox" id="onlyValid" checked={onlyValidEmail} onChange={e=>setOnlyValidEmail(e.target.checked)}
              style={{ width:16, height:16, accentColor:'var(--accent)', cursor:'pointer' }} />
            <label htmlFor="onlyValid" style={{ fontSize:13, color:'var(--text-2)', cursor:'pointer' }}>Only send to leads with a verified email</label>
            {eligibleCount !== null && (
              <span style={{ fontSize:12, color:'var(--text-3)', marginLeft:'auto' }}>{eligibleCount} lead(s) will receive this email</span>
            )}
          </div>

          <input className="input" placeholder="Subject — e.g. Quick question for {{company}}"
            value={emailSubject} onChange={e=>setEmailSubject(e.target.value)} />
          <textarea className="input" rows={6} placeholder="Hi {{name}}, ..."
            value={emailBody} onChange={e=>setEmailBody(e.target.value)} style={{ resize:'vertical', fontFamily:'inherit' }} />

          {emailError && (
            <div style={{ padding:'9px 12px', background:'#fff1f2', border:'1.5px solid #fca5a5', borderRadius:8, color:'#9f1239', fontSize:13 }}>
              {emailError}
            </div>
          )}

          {campaign && (
            <div style={{ padding:'10px 14px', borderRadius:8, fontSize:13, background:'#f0fdf4', border:'1.5px solid #86efac', color:'#166534' }}>
              {campaign.status === 'completed'
                ? `Done — sent ${campaign.sent_count}, failed ${campaign.failed_count} of ${campaign.total}.`
                : `Sending… ${campaign.sent_count}/${campaign.total} sent (${campaign.failed_count} failed).`}
            </div>
          )}

          <div style={{ display:'flex', justifyContent:'flex-end' }}>
            <button className="btn-primary" onClick={sendBulkEmail}
              disabled={emailSending || !emailSubject || !emailBody || !eligibleCount || (campaign && campaign.status!=='completed' && campaign.status!=='failed')}
              style={{ height:38, padding:'0 18px', fontSize:13 }}>
              {emailSending ? 'Starting…' : `Send to ${eligibleCount ?? '…'} lead(s)`}
            </button>
          </div>
        </div>
      )}

      {/* Leads table */}
      <LeadsTable leads={leads} />

      <style>{`
        @keyframes spin { from{transform:rotate(0deg)} to{transform:rotate(360deg)} }
      `}</style>
    </div>
  );
}
