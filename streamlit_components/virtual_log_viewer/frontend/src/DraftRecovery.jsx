import React, {useEffect, useRef, useState} from "react";
import {Streamlit} from "streamlit-component-lib";
import {readBrowserDrafts} from "./browserDraft.mjs";

export default function DraftRecovery() {
  const root = useRef(null);
  const [drafts,setDrafts] = useState([]);
  const [error,setError] = useState("");
  useEffect(() => {
    const refresh = () => {
      try { setDrafts(readBrowserDrafts()); setError(""); }
      catch (_) { setError("Browser draft storage is unavailable. Use a saved session file."); }
    };
    refresh();
    window.addEventListener("storage",refresh);
    const resize = new ResizeObserver(() => Streamlit.setFrameHeight(Math.ceil(root.current?.getBoundingClientRect().height || 40)));
    resize.observe(root.current);
    return () => { window.removeEventListener("storage",refresh); resize.disconnect(); };
  },[]);
  return <div ref={root} style={{fontFamily:"Arial,sans-serif",fontSize:13,color:"#31333f",padding:"4px 0"}}>
    <details>
      <summary style={{cursor:"pointer"}}>Recover browser draft ({drafts.length})</summary>
      <p>Restore work kept in this browser after a refresh or interruption. Restoring replaces the current session.</p>
      {error && <p>{error}</p>}
      {!drafts.length && !error && <p>No browser drafts are available yet.</p>}
      {drafts.map(draft => <div key={draft.context_key+draft.browser_session_token} data-draft-owner={draft.browser_session_token} data-draft-context={draft.context_key} style={{margin:"10px 0",borderTop:"1px solid #ddd",paddingTop:6}}>
        <div><b>{draft.selected_well || draft.context_key}</b> · {(draft.selected_sections || []).join(", ")} · {draft.selected_agent || "data agent"}</div>
        <div>{draft.tags.length} tag(s){draft.saved_at ? " · "+new Date(draft.saved_at).toLocaleString() : " · previous session"}</div>
        {!draft.session_base && <div>Older draft: tags and view only. Verify agent settings after recovery.</div>}
        <button type="button" style={{marginTop:4,padding:"5px 9px",cursor:"pointer"}} onClick={() => Streamlit.setComponentValue({
          event:"recover_browser_draft",request_id:window.crypto?.randomUUID?.() || String(Date.now()),
          snapshot:draft,
        })}>Restore this draft</button>
      </div>)}
    </details>
  </div>;
}
