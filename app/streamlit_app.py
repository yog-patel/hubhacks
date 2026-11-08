"""AquaLens AI - Streamlit app.   Run:  streamlit run app/streamlit_app.py

Pages: Analyze, Results, Verify counts, Review queue, Species registry, Model & privacy. Everything runs on this computer.
UI code lives in app/ui/ (design tokens in app/ui/theme.py); the pipeline lives in src/bluesight/.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))   # bluesight package (sets offline mode on import)
sys.path.insert(0, str(ROOT / "app"))   # ui package

import bluesight  # noqa: E402,F401  (must come first: switches Hugging Face to offline mode)
import streamlit as st  # noqa: E402

st.set_page_config(page_title="AquaLens AI", page_icon=":material/water:", layout="wide",
                   initial_sidebar_state="expanded")

from ui import common as C  # noqa: E402
from ui import page_analyze, page_assisted, page_privacy, page_registry, page_results, page_review, theme  # noqa: E402

theme.inject()
st.logo(str(ROOT / "app" / "assets" / ("logo-dark.svg" if theme.is_dark() else "logo.svg")), size="large",
        icon_image=str(ROOT / "app" / "assets" / "icon.svg"))
C.base_config()

pending = C.pending_count()
pages = {
    "analyze": st.Page(page_analyze.page, title="Analyze", icon=":material/play_circle:", url_path="analyze", default=True),
    "results": st.Page(page_results.page, title="Results", icon=":material/bar_chart:", url_path="results"),
    "assisted": st.Page(page_assisted.page, title="Verify counts", icon=":material/ads_click:", url_path="verify"),
    "review": st.Page(page_review.page, title=f"Review queue ({pending})" if pending else "Review queue",
                      icon=":material/fact_check:", url_path="review"),
    "registry": st.Page(page_registry.page, title="Species registry", icon=":material/collections_bookmark:", url_path="registry"),
    "privacy": st.Page(page_privacy.page, title="Model & privacy", icon=":material/verified_user:", url_path="privacy"),
}
C.PAGES.update(pages)
nav = st.navigation({"Survey": [pages["analyze"], pages["results"], pages["assisted"], pages["review"]],
                     "Reference": [pages["registry"], pages["privacy"]]})
C.sidebar()
nav.run()
