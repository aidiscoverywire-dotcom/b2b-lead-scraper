function TierBadge({ tier }) {
  const t = (tier || 'basic').toLowerCase();
  const map = {
    full:    { cls:'badge-green',  label:'Full' },
    company: { cls:'badge-amber',  label:'Company' },
    basic:   { cls:'badge-gray',   label:'Basic' },
  };
  const { cls, label } = map[t] || map.basic;
  return <span className={`badge ${cls}`}>{label}</span>;
}

function StarRating({ value }) {
  if (value == null) return <span style={{ color:'var(--text-3)' }}>—</span>;
  const n = Number(value).toFixed(1);
  const filled = Math.round(value);
  return (
    <span style={{ display:'flex', alignItems:'center', gap:4 }}>
      <span style={{ color:'#f59e0b', fontSize:12 }}>
        {'★'.repeat(filled)}{'☆'.repeat(5-filled)}
      </span>
      <span style={{ fontSize:12, fontWeight:600, color:'var(--text-1)' }}>{n}</span>
    </span>
  );
}

function ScoreBadge({ score }) {
  if (score == null) return <span style={{ color:'var(--text-3)' }}>—</span>;
  const s = Number(score);
  const color = s >= 80 ? '#10b981' : s >= 60 ? '#f59e0b' : '#64748b';
  return (
    <div style={{
      display:'inline-flex', alignItems:'center', justifyContent:'center',
      width:34, height:34, borderRadius:'50%',
      background:`${color}18`, border:`1.5px solid ${color}40`,
      color, fontWeight:700, fontSize:12,
    }}>
      {s}
    </div>
  );
}

export default function LeadsTable({ leads }) {
  if (!leads.length) {
    return (
      <div className="card" style={{ padding:'48px 20px', textAlign:'center' }}>
        <div style={{ fontSize:40, marginBottom:12 }}>🧲</div>
        <p style={{ color:'var(--text-3)', fontSize:14, fontWeight:500, margin:0 }}>
          No leads yet — start a search above and results will appear here in real time.
        </p>
      </div>
    );
  }

  return (
    <div className="card" style={{ overflow:'hidden' }}>
      {/* Count header */}
      <div style={{ padding:'10px 16px', borderBottom:'1.5px solid var(--border)', display:'flex', alignItems:'center', gap:8 }}>
        <span style={{ fontSize:13, fontWeight:600, color:'var(--text-1)' }}>{leads.length} leads</span>
        <span className="badge badge-indigo">{leads.filter(l=>l.decision_maker_email||l.email).length} with email</span>
        <span className="badge badge-green">{leads.filter(l=>(l.enrichment_status||'basic')==='full').length} fully enriched</span>
      </div>

      <div style={{ overflowX:'auto' }}>
        <table className="data-table">
          <thead>
            <tr>
              <th>#</th>
              <th>Business Name</th>
              <th>Address</th>
              <th>Phone</th>
              <th>Website</th>
              <th>Rating</th>
              <th>Reviews</th>
              <th>Enrichment</th>
              <th>Email</th>
              <th>Pitch</th>
              <th>Score</th>
            </tr>
          </thead>
          <tbody>
            {leads.map((lead, i) => {
              const email = lead.decision_maker_email || lead.email;
              return (
                <tr key={lead.place_id || i}>
                  <td style={{ color:'var(--text-3)', fontSize:12, width:36 }}>{i+1}</td>
                  <td style={{ fontWeight:600, maxWidth:180 }}>
                    <div style={{ overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap' }} title={lead.name}>
                      {lead.name || '—'}
                    </div>
                  </td>
                  <td style={{ color:'var(--text-2)', maxWidth:200 }}>
                    <div style={{ overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap', fontSize:12 }} title={lead.address}>
                      {lead.address || '—'}
                    </div>
                  </td>
                  <td>
                    {lead.phone
                      ? <a href={`tel:${lead.phone}`} style={{ color:'var(--accent)', textDecoration:'none', fontWeight:500, fontSize:12, whiteSpace:'nowrap' }}>{lead.phone}</a>
                      : <span style={{ color:'var(--text-3)' }}>—</span>}
                  </td>
                  <td>
                    {lead.website
                      ? <a href={lead.website} target="_blank" rel="noreferrer"
                          style={{ color:'var(--accent)', textDecoration:'none', fontWeight:500, fontSize:12 }}>
                          {(() => { try { return new URL(lead.website).hostname.replace(/^www\./,''); } catch { return 'link'; } })()}
                        </a>
                      : <span style={{ color:'var(--text-3)' }}>—</span>}
                  </td>
                  <td><StarRating value={lead.rating} /></td>
                  <td style={{ fontWeight:600 }}>{lead.review_count ?? <span style={{color:'var(--text-3)'}}>—</span>}</td>
                  <td><TierBadge tier={lead.enrichment_status} /></td>
                  <td>
                    {email
                      ? <div>
                          <div style={{ fontSize:12, fontWeight:500, color:'var(--text-1)' }}>{email}</div>
                          <div style={{ fontSize:11, color:'var(--text-3)' }}>{lead.email_status||'found'}</div>
                        </div>
                      : <span style={{ fontSize:12, color:'var(--text-3)' }}>{lead.email_status||'—'}</span>}
                  </td>
                  <td style={{ maxWidth:220 }}>
                    <div style={{ fontSize:12, color:'var(--text-2)', overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap' }} title={lead.pitch}>
                      {lead.pitch || <span style={{color:'var(--text-3)'}}>—</span>}
                    </div>
                  </td>
                  <td><ScoreBadge score={lead.lead_score} /></td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
