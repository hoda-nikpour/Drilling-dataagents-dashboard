export function downloadText(text,mime,name) {
  let host = window;
  try { if (window.parent?.document) host = window.parent; } catch (_) {}
  const doc = host.document;
  const url = host.URL.createObjectURL(new host.Blob([text],{type:mime}));
  const link = doc.createElement("a");
  link.href=url;link.download=name;
  doc.body.appendChild(link);link.click();link.remove();
  // The owning page survives component reruns and file/session changes.
  host.setTimeout(() => host.URL.revokeObjectURL(url),1000);
}
