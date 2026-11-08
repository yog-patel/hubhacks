"""BlueSight AI - Streamlit app.   Run:  streamlit run app/streamlit_app.py

Pages: Analyze, Results, Review queue, Species registry, Model & privacy. Everything runs on this computer.
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

st.set_page_config(page_title="BlueSight AI", page_icon=":material/water:", layout="wide",
                   initial_sidebar_state="expanded")

from ui import common as C  # noqa: E402
from ui import (page_analyze, page_check, page_guide, page_privacy, page_registry, page_results, page_review,  # noqa: E402
                theme)

theme.inject()
st.logo(str(ROOT / "app" / "assets" / ("logo-dark.svg" if theme.is_dark() else "logo.svg")), size="large",
        icon_image=str(ROOT / "app" / "assets" / "icon.svg"))
C.base_config()

pending = C.pending_count()
pages = {
    "guide": st.Page(page_guide.page, title="Help", icon=":material/help:", url_path="guide"),
    "analyze": st.Page(page_analyze.page, title="Analyze", icon=":material/play_circle:", url_path="analyze", default=True),
    "check": st.Page(page_check.page, title="Check counts", icon=":material/rule:", url_path="check"),
    "results": st.Page(page_results.page, title="Report", icon=":material/bar_chart:", url_path="results"),
    "review": st.Page(page_review.page, title=f"New animals ({pending})" if pending else "New animals",
                      icon=":material/pets:", url_path="review"),
    "registry": st.Page(page_registry.page, title="Species", icon=":material/collections_bookmark:", url_path="registry"),
    "privacy": st.Page(page_privacy.page, title="Privacy", icon=":material/verified_user:", url_path="privacy"),
}
C.PAGES.update(pages)
nav = st.navigation({"Survey": [pages["analyze"], pages["check"], pages["review"], pages["results"]],
                     "Library": [pages["registry"], pages["privacy"], pages["guide"]]})
C.sidebar()
nav.run()
