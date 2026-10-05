import { useState } from 'react';
import { api, ENDPOINTS } from '../api';

const inputCls =
  'w-full border border-violet-200 rounded-xl px-3 py-2 focus:outline-none focus:ring-2 focus:ring-violet-500 focus:border-violet-400';
const btnPrimary =
  'bg-gradient-to-r from-indigo-600 to-violet-600 hover:opacity-95 disabled:opacity-50 text-white font-bold rounded-xl px-5 py-2 shadow-md shadow-violet-300';
const btnGhost =
  'border border-violet-200 hover:bg-violet-50 text-violet-700 font-medium rounded-xl px-5 py-2';

function TestResult({ result }) {
  if (!result) return null;
  if (result.ok)
    return <p className="text-sm text-green-700 bg-green-50 border border-green-200 rounded-lg px-3 py-2 mt-2">✓ {result.message}</p>;
  return <p className="text-sm text-red-700 bg-red-50 border border-red-200 rounded-lg px-3 py-2 mt-2">✕ {result.message}</p>;
}

/**
 * 3-step first-run wizard (blueprint §5). NO proxy step.
 * Step 1: OpenAI key + test (POST /api/wizard/test-openai)
 * Step 2: Apollo key + test (POST /api/wizard/test-apollo), SKIPPABLE, tier notice shown
 * Step 3: Google Maps key + test (POST /api/wizard/test-maps, searchText pageSize=1)
 * Finish -> POST /api/wizard/complete
 */
export default function Wizard({ onDone }) {
  const [step, setStep] = useState(1);
  const [keys, setKeys] = useState({ openai: '', apollo: '', google: '' });
  const [results, setResults] = useState({ openai: null, apollo: null, google: null });
  const [testing, setTesting] = useState(false);
  const [finishing, setFinishing] = useState(false);
  const [error, setError] = useState('');

  const setKey = (k, v) => {
    setKeys((p) => ({ ...p, [k]: v }));
    setResults((p) => ({ ...p, [k]: null }));
  };

  const testKey = async (which) => {
    const endpoint =
      which === 'openai' ? ENDPOINTS.wizardTestOpenAI :
      which === 'apollo' ? ENDPOINTS.wizardTestApollo : ENDPOINTS.wizardTestMaps;
    setTesting(true);
    setError('');
    try {
      const res = await api.post(endpoint, { key: keys[which] });
      // Backend always returns HTTP 200 with {ok, message} — a 200 does NOT
      // mean the key works; honor res.data.ok explicitly.
      const ok = res.data?.ok === true;
      const hint = res.data?.tier_hint || res.data?.message || (ok ? 'Key works.' : 'Key test failed.');
      setResults((p) => ({ ...p, [which]: { ok, message: hint } }));
    } catch (err) {
      const msg = err.response?.data?.detail || err.response?.data?.message || 'Key test failed. Check the key and try again.';
      setResults((p) => ({ ...p, [which]: { ok: false, message: msg } }));
    } finally {
      setTesting(false);
    }
  };

  const KEY_NAMES = { openai: 'openai_key', apollo: 'apollo_key', google: 'google_maps_key' };

  const saveKey = async (which) => {
    if (!keys[which]) return;
    await api.put(ENDPOINTS.settings, { key_name: KEY_NAMES[which], value: keys[which] });
  };

  const nextFrom = async (which) => {
    setError('');
    try {
      if (keys[which]) await saveKey(which);
    } catch (err) {
      setError('Key tested OK but saving failed — please try again.');
      return;
    }
    setStep(which === 'openai' ? 2 : 3);
  };

  const finish = async () => {
    setFinishing(true);
    setError('');
    try {
      await saveKey('google');
      await api.post(ENDPOINTS.wizardComplete);
    } catch (err) {
      // Do NOT mark setup complete when the required Google key failed to
      // save — the user would otherwise be stuck thinking search is unlocked.
      const msg = err.response?.data?.detail || 'Could not save your Google Places key. Please try again.';
      setError(msg);
      setFinishing(false);
      return;
    }
    localStorage.setItem('ls_wizard_done', '1');
    setFinishing(false);
    onDone();
  };

  const steps = ['OpenAI', 'Apollo', 'Google Maps'];

  return (
    <div className="min-h-screen bg-gradient-to-br from-indigo-600 via-violet-600 to-fuchsia-600 flex items-center justify-center p-4">
      <div className="bg-white rounded-2xl shadow-2xl p-8 w-full max-w-lg">
        <div className="flex items-center gap-3 mb-1">
          <img src="/logo.png" alt="logo" className="w-12 h-12 rounded-xl shadow" />
          <h1 className="text-xl font-extrabold bg-gradient-to-r from-indigo-600 to-fuchsia-600 bg-clip-text text-transparent">Welcome — let's set up your keys</h1>
        </div>
        <p className="text-sm text-slate-500 mb-6">Your keys are stored encrypted on your own server. You pay Google / Apollo / OpenAI directly — nothing goes through us.</p>

        <div className="flex gap-2 mb-8">
          {steps.map((label, i) => (
            <div key={label} className="flex-1">
              <div className={`h-2.5 rounded-full ${step > i + 1 || (step === 3 && i === 2 && results.google?.ok) ? 'bg-gradient-to-r from-indigo-500 to-fuchsia-500' : step === i + 1 ? 'bg-violet-300' : 'bg-slate-200'}`} />
              <p className={`text-xs mt-1 ${step === i + 1 ? 'font-bold text-violet-700' : 'text-slate-400'}`}>{i + 1}. {label}</p>
            </div>
          ))}
        </div>

        {step === 1 && (
          <div>
            <h2 className="font-semibold text-slate-700 mb-1">Step 1 — OpenAI API key <span className="text-slate-400 font-normal">(optional)</span></h2>
            <p className="text-sm text-slate-500 mb-3">Used to write short pitch lines and lead scores. Get one at platform.openai.com → API keys. You can skip this — leads still collect fine without AI pitches.</p>
            <input type="password" placeholder="sk-…" value={keys.openai} onChange={(e) => setKey('openai', e.target.value)} className={inputCls} />
            <TestResult result={results.openai} />
            {error && <p className="text-sm text-red-600 mt-2">{error}</p>}
            <div className="flex justify-end gap-2 mt-4">
              <button onClick={() => setStep(2)} className={btnGhost}>Skip</button>
              <button disabled={!keys.openai || testing} onClick={() => testKey('openai')} className={btnGhost}>
                {testing ? 'Testing…' : 'Test key'}
              </button>
              <button disabled={!!keys.openai && !results.openai?.ok} onClick={() => nextFrom('openai')} className={btnPrimary}>Next</button>
            </div>
          </div>
        )}

        {step === 2 && (
          <div>
            <h2 className="font-semibold text-slate-700 mb-1">Step 2 — Apollo API key <span className="text-slate-400 font-normal">(optional)</span></h2>
            <p className="text-sm text-slate-500 mb-3">Adds company info and decision-maker emails. Free key = limited monthly reveal pool (~75/mo per reports — verify). Basic $49/mo unlocks full-volume emails. You can skip this — the tool works on Google data alone.</p>
            <input type="password" placeholder="Apollo API key" value={keys.apollo} onChange={(e) => setKey('apollo', e.target.value)} className={inputCls} />
            <TestResult result={results.apollo} />
            {error && <p className="text-sm text-red-600 mt-2">{error}</p>}
            <div className="flex justify-end gap-2 mt-4">
              <button onClick={() => setStep(3)} className={btnGhost}>Skip</button>
              <button disabled={!keys.apollo || testing} onClick={() => testKey('apollo')} className={btnGhost}>
                {testing ? 'Testing…' : 'Test key'}
              </button>
              <button disabled={!results.apollo?.ok} onClick={() => nextFrom('apollo')} className={btnPrimary}>Next</button>
            </div>
          </div>
        )}

        {step === 3 && (
          <div>
            <h2 className="font-semibold text-slate-700 mb-1">Step 3 — Google Maps API key</h2>
            <p className="text-sm text-slate-500 mb-3">
              Used for business data via the official Places API (New).{' '}
              <span className="font-medium text-slate-700">Enable "Places API (New)" in Google Cloud Console</span>{' '}
              for your project, then paste the key below.
            </p>
            <input type="password" placeholder="Google Maps API key" value={keys.google} onChange={(e) => setKey('google', e.target.value)} className={inputCls} />
            <TestResult result={results.google} />
            {error && <p className="text-sm text-red-600 mt-2">{error}</p>}
            <div className="flex justify-between mt-4">
              <button onClick={() => setStep(2)} className={btnGhost}>Back</button>
              <div className="flex gap-2">
                <button disabled={!keys.google || testing} onClick={() => testKey('google')} className={btnGhost}>
                  {testing ? 'Testing…' : 'Test key'}
                </button>
                <button disabled={!results.google?.ok || finishing} onClick={finish} className={btnPrimary}>
                  {finishing ? 'Finishing…' : 'Finish setup'}
                </button>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
