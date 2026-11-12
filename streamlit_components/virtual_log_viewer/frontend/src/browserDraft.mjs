const PREFIX = "drillmate_recovery_v1_";
let memoryTabId = null;

function tabId() {
  if (!memoryTabId) memoryTabId = window.crypto?.randomUUID?.() || String(Date.now())+Math.random();
  try {
    const key = "drillmate_recovery_tab";
    let value = sessionStorage.getItem(key);
    if (!value) { value = memoryTabId; sessionStorage.setItem(key,value); }
    return value;
  } catch (_) { return memoryTabId; }
}

export function storeBrowserDraft(snapshot) {
  const key = PREFIX+JSON.stringify([tabId(),snapshot.context_key,snapshot.selected_agent]);
  const raw = localStorage.getItem(key);
  let old = null;
  try { old = JSON.parse(raw || "null"); } catch (_) {}
  // Preserve the preceding editor's unsaved work when a different session is
  // loaded and then edited. Fresh empty startup never calls this function.
  if (old && old.browser_session_token !== snapshot.browser_session_token) {
    localStorage.setItem(PREFIX+"archive_"+old.context_key+"_"+old.browser_session_token,JSON.stringify(old));
  }
  localStorage.setItem(key,JSON.stringify(snapshot));
}

export function readBrowserDrafts() {
  const drafts = new Map();
  for (let i=0; i<localStorage.length; i++) {
    const key = localStorage.key(i);
    if (!key?.startsWith(PREFIX) && !key?.startsWith("hoda_dashboard_snapshot_")) continue;
    try {
      const snapshot = JSON.parse(localStorage.getItem(key));
      if (snapshot?.schema_version !== 1 || !snapshot.context_key || !Array.isArray(snapshot.tags)) continue;
      if (!snapshot.tags.length && !snapshot.deleted_tag_ids?.length) continue;
      const identity = snapshot.context_key+"|"+snapshot.browser_session_token;
      const current = drafts.get(identity);
      if (!current || (snapshot.sequence || 0) > (current.sequence || 0) || (!current.session_base && snapshot.session_base)) {
        drafts.set(identity,snapshot);
      }
    } catch (_) { /* A malformed draft must not prevent other recovery. */ }
  }
  return [...drafts.values()].sort((a,b) => String(b.saved_at || "").localeCompare(String(a.saved_at || "")));
}
