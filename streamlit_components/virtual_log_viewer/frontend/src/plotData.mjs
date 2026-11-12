const validNumber = value => value !== null && value !== undefined && value !== "" && Number.isFinite(Number(value));

export function normalizeValues(values, minimum = null, maximum = null) {
  const numbers = values.filter(validNumber).map(Number);
  let low = validNumber(minimum) ? Number(minimum) : null;
  let high = validNumber(maximum) ? Number(maximum) : null;
  if (low === null || high === null) {
    if (!numbers.length) return values.map(() => null);
    low = Infinity; high = -Infinity;
    for (const value of numbers) { low = Math.min(low, value); high = Math.max(high, value); }
  }
  return values.map(value => !validNumber(value) ? null
    : Math.abs(high - low) < 1e-12 ? .5
    : (Math.max(low, Math.min(high, Number(value))) - low) / (high - low));
}

function lowerBound(rows, time) {
  let left = 0, right = rows.length;
  while (left < right) {
    const middle = (left + right) >> 1;
    if (rows[middle].time < time) left = middle + 1;
    else right = middle;
  }
  return left;
}

export function buildHoverIndex(trackData, parseTime) {
  const breaks = new Set(trackData?.gap_after_indices || []);
  return new Map((trackData?.tracks || []).map(track => {
    const curves = track.curves || [];
    const times = (curves[0]?.y || []).map(parseTime);
    const rows = times.map((time, index) => ({time, index}))
      .filter(row => Number.isFinite(row.time)).sort((a,b) => a.time-b.time || a.index-b.index);
    return [Number(track.track), {rows, breaks, curves: curves.map(curve => ({
      ...curve, normalized: normalizeValues(curve.x || [],curve.display_min,curve.display_max),
    }))}];
  }));
}

export function closestHoverPoint(index, trackNo, time, cursorX) {
  const track = index.get(trackNo);
  if (!track?.rows.length || !Number.isFinite(time)) return null;
  const rows = track.rows, next = lowerBound(rows,time);
  const before = rows[next-1], after = rows[next];
  if (before && after && time > before.time && time < after.time && track.breaks.has(before.index)) return null;
  const nearest = !before ? after : !after ? before
    : time-before.time <= after.time-time ? before : after;
  let best = null;
  // Only the closest recorded timestamp is eligible. Duplicate timestamps can
  // have distinct measurements; choose the actual point closest in X.
  for (let position = lowerBound(rows,nearest.time); position < rows.length && rows[position].time === nearest.time; position++) {
    const row = rows[position].index;
    for (const curve of track.curves) {
      const raw = curve.x?.[row], x = curve.normalized[row];
      if (!validNumber(raw) || !Number.isFinite(x)) continue;
      const distance = Math.abs(x-cursorX);
      if (!best || distance < best.distance) best = {
        distance, label: curve.label || curve.raw_col || "Value", unit: curve.unit || "",
        value: Number(raw), timeMs: nearest.time, row,
      };
    }
  }
  return best;
}

export function boundedTagTimes(a,b,sectionStart,sectionEnd) {
  if (!Number.isFinite(a) || !Number.isFinite(b)) return null;
  const first = Number.isFinite(sectionStart) ? Math.ceil(sectionStart/1000)*1000 : -Infinity;
  const last = Number.isFinite(sectionEnd) ? Math.floor(sectionEnd/1000)*1000 : Infinity;
  let start = Math.max(first,Math.min(last,Math.round(Math.min(a,b)/1000)*1000));
  let end = Math.max(first,Math.min(last,Math.round(Math.max(a,b)/1000)*1000));
  if (end <= start) {
    if (start+1000 <= last) end = start+1000;
    else if (end-1000 >= first) start = end-1000;
    else return null;
  }
  return [start,end];
}
