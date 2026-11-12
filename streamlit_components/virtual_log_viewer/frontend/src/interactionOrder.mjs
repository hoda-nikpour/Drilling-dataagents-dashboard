let previous = 0;

export function nextInteractionOrder(minimum = 0) {
  let host;
  try { host = window.parent; previous = Math.max(previous,Number(host.__drillmateInteractionOrder || 0)); } catch (_) {}
  previous = Math.max(Date.now(),previous+1,Number(minimum || 0)+1);
  try { host.__drillmateInteractionOrder = previous; } catch (_) {}
  return previous;
}
