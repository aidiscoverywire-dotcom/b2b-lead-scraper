export default function ProgressBar({ progress }) {
  const { leads=0, requested=0, searches=0, details=0, apolloCredits=0, status='idle' } = progress || {};
  const pct = requested > 0 ? Math.min(100, Math.round((leads / requested) * 100)) : 0;
  const googleCost = (searches * 0.032 + details * 0.02).toFixed(2);

  const statusConfig = {
    idle:    { label:'Ready to search', color:'var(--text-3)', dot:'#94a3b8' },
    running: { label:'Searching…',      color:'var(--accent)',  dot:'#6366f1' },
    done:    { label:'Complete',         color:'var(--green)',   dot:'#10b981' },
    error:   { label:'Error',            color:'var(--red)',     dot:'#ef4444' },
  }[status] || { label:status, color:'var(--text-2)', dot:'#94a3b8' };

  const isRunning = status === 'running';

  return (
    <div className="card" style={{ padding:'14px 18px' }}>
      <div style={{ display:'flex', alignItems:'center', gap:16, flexWrap:'wrap', marginBottom:10 }}>
        {/* Status dot */}
        <div style={{ display:'flex', alignItems:'center', gap:7 }}>
          <span style={{
            width:8, height:8, borderRadius:'50%', background:statusConfig.dot, flexShrink:0,
            boxShadow: isRunning ? `0 0 0 3px rgba(99,102,241,.2)` : 'none',
          }} />
          <span style={{ fontSize:13, fontWeight:600, color:statusConfig.color }}>{statusConfig.label}</span>
        </div>

        {/* Lead count */}
        <div style={{ fontSize:13, color:'var(--text-2)' }}>
          <span style={{ fontWeight:700, color:'var(--text-1)', fontSize:15 }}>{leads}</span>
          {requested > 0 && <span style={{ color:'var(--text-3)' }}> / {requested} leads</span>}
        </div>

        <div style={{ flex:1 }} />

        {/* Cost pills */}
        <div style={{ display:'flex', gap:8, flexWrap:'wrap' }}>
          <span className="badge badge-indigo">
            <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>
            Google: ${googleCost}
          </span>
          <span className="badge badge-amber">
            Apollo credits: {apolloCredits}
          </span>
          {(searches > 0 || details > 0) && (
            <span className="badge badge-gray">
              {searches} searches · {details} details
            </span>
          )}
        </div>
      </div>

      {/* Bar */}
      <div className="progress-track">
        <div
          className={`progress-fill${status==='error'?' error':''}`}
          style={{ width:`${pct}%` }}
        />
      </div>
      {requested > 0 && (
        <div style={{ fontSize:11, color:'var(--text-3)', marginTop:5, textAlign:'right' }}>{pct}%</div>
      )}
    </div>
  );
}
