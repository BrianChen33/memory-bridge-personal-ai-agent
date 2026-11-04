// sticker_emotion.mjs — Shared emotion intensity for sticker probability
// (2026-11-03, master-authorized: emotion layer integration)
//
// Intensity source: ACTUAL decayed mood from brain.py emotion layer.
// - QQ: mood comes from result.brain (this round's prepare-updated mood)
// - Main chat: mood read via official brain.py op='mood' (one bounded local read)
//
// Formula:
//   I = clamp(max(sqrt((p²+a²+d²)/3), max_valid_label_intensity/0.6), 0, 1)
//   - Neutral PAD = 0 → I=0
//   - Label max 0.6 (from emotion layer) normalized to 0..1
//   - RMS of PAD captures overall emotional activation
//
// Probability:
//   p = base + (max-base)*I
//   - base=0.40, max=1.00 (configurable)
//   - I=0 → 40%, I=0.5 → 70%, I=1 → 100%
//
// Rules:
// - Emotion ONLY affects casual auto-stickers (not explicit requests, not serious topics)
// - Missing/error mood → degrade to base probability, mark unavailable (never fabricate)
// - NEVER modify or accumulate emotion state for sticker sending (read-only)

export function clamp(v, lo, hi) {
  return Math.max(lo, Math.min(hi, v));
}

/**
 * Normalize mood to intensity I in [0,1].
 * @param {object|null} mood - {p, a, d, labels:[{label,intensity}], ...} or null
 * @returns {{intensity:number, available:boolean, reason:string}}
 */
export function normalizeIntensity(mood) {
  if (!mood || typeof mood !== 'object') {
    return { intensity: 0, available: false, reason: 'mood_missing' };
  }
  
  // Reject if mood is marked disabled/degraded/failed
  // (brain.py returns {ok:false} or {disabled:true} on failure)
  if (mood.ok === false || mood.disabled === true || mood.degraded === true) {
    return { intensity: 0, available: false, reason: 'mood_unavailable' };
  }
  
  // Strict validation: p, a, d must be actual numbers (not null, not strings),
  // finite, and in [-1, 1] range (brain.py clamps to this range)
  const p = mood.p;
  const a = mood.a;
  const d = mood.d;
  
  const isValidNumber = (v) => typeof v === 'number' && Number.isFinite(v) && v >= -1 && v <= 1;
  
  if (!isValidNumber(p) || !isValidNumber(a) || !isValidNumber(d)) {
    return { intensity: 0, available: false, reason: 'mood_invalid_pad' };
  }
  
  // RMS of PAD: sqrt((p²+a²+d²)/3)
  // Neutral (0,0,0) → 0. Max (|1|,|1|,|1|) → 1.
  const rms = Math.sqrt((p*p + a*a + d*d) / 3);
  
  // Max valid label intensity, normalized by 0.6 (emotion layer max)
  // Labels must have finite intensity in (0.01, 0.6] to be valid
  let maxLabelNorm = 0;
  if (Array.isArray(mood.labels)) {
    for (const l of mood.labels) {
      if (!l || typeof l !== 'object') continue;
      const inten = l.intensity;
      // Strict: must be number, finite, >0.01 (brain.py threshold), ≤0.6 (max)
      if (typeof inten === 'number' && Number.isFinite(inten) && inten > 0.01 && inten <= 0.6) {
        maxLabelNorm = Math.max(maxLabelNorm, inten / 0.6);
      }
      // Invalid label values are IGNORED (do not boost, do not fail)
    }
  }
  
  const intensity = clamp(Math.max(rms, maxLabelNorm), 0, 1);
  return { intensity, available: true, reason: 'ok' };
}

/**
 * Compute sticker probability from intensity.
 * @param {number} intensity - I in [0,1]
 * @param {object} policy - {base_probability, max_probability}
 * @returns {number} probability in [0,1]
 */
export function probabilityFromIntensity(intensity, policy = {}) {
  const base = Number(policy.base_probability ?? 0.40);
  const max = Number(policy.max_probability ?? 1.00);
  
  // Validate: 0 ≤ base ≤ max ≤ 1
  const b = clamp(Number.isFinite(base) ? base : 0.40, 0, 1);
  const m = clamp(Number.isFinite(max) ? max : 1.00, 0, 1);
  const baseClamped = Math.min(b, m);
  
  const I = clamp(Number.isFinite(intensity) ? intensity : 0, 0, 1);
  return baseClamped + (m - baseClamped) * I;
}

/**
 * Compute shared intensity from global and local moods.
 * I = max(I_global, I_local) — both use same normalized decayed values.
 * If one source missing → drop that source; if both unavailable → base.
 * 
 * @param {object|null} globalMood - owner-private mood (shared background)
 * @param {object|null} localMood - QQ scope mood (local)
 * @returns {{intensity:number, available:boolean, reason:string, sources:string[]}}
 */
export function sharedIntensity(globalMood, localMood) {
  const g = normalizeIntensity(globalMood);
  const l = normalizeIntensity(localMood);
  
  const sources = [];
  let intensity = 0;
  
  if (g.available) {
    sources.push('global');
    intensity = Math.max(intensity, g.intensity);
  }
  if (l.available) {
    sources.push('local');
    intensity = Math.max(intensity, l.intensity);
  }
  
  if (sources.length === 0) {
    return { intensity: 0, available: false, reason: 'both_unavailable', sources: [] };
  }
  
  return { 
    intensity: clamp(intensity, 0, 1), 
    available: true, 
    reason: `shared:${sources.join('+')}`,
    sources 
  };
}
