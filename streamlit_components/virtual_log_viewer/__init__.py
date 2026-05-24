from pathlib import Path

import streamlit.components.v1 as components


_FRONTEND_DIR = Path(__file__).parent / "frontend"
_DIST_DIR = _FRONTEND_DIR / "dist"
_INDEX_HTML = _DIST_DIR / "index.html"


def _validate_dist_build() -> str:
    if not _DIST_DIR.exists() or not _INDEX_HTML.exists():
        raise RuntimeError(
            "Virtual log viewer frontend build is missing. Run:\n\n"
            "cd streamlit_components/virtual_log_viewer/frontend\n"
            "npm install\n"
            "npm run build\n"
        )

    index_text = _INDEX_HTML.read_text(encoding="utf-8", errors="ignore")

    if 'src="/assets/' in index_text or 'href="/assets/' in index_text:
        raise RuntimeError(
            "Virtual log viewer dist build is invalid: dist/index.html uses absolute /assets paths.\n"
            "This breaks Streamlit component deployment.\n\n"
            "Fix frontend/vite.config.js with base: './', then rebuild:\n\n"
            "cd streamlit_components/virtual_log_viewer/frontend\n"
            "rm -rf dist build\n"
            "npm install\n"
            "npm run build\n"
        )

    return str(_DIST_DIR)


virtual_log_viewer = components.declare_component(
    "virtual_log_viewer",
    path=_validate_dist_build(),
)


def render_virtual_log_viewer(**kwargs):
    context_key = kwargs.get("context_key", "default")
    key = kwargs.pop("key", f"virtual_log_viewer_{context_key}")
    return virtual_log_viewer(key=key, default=None, **kwargs)