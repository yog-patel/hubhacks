#!/bin/bash
# BlueSight AI - double-click to start. First start installs everything (needs internet once, 10-20 min).
# After that it starts in under a minute and works with the internet off.
cd "$(dirname "$0")" || exit 1

if [ ! -x ".venv/bin/python" ]; then
  echo
  echo " First-time setup. This needs the internet ONCE and takes 10-20 minutes."
  echo " It installs Python packages and downloads the open-source AI models into this folder."
  echo
  if ! command -v uv >/dev/null 2>&1; then
    echo " Installing uv, a small Python installer..."
    curl -LsSf https://astral.sh/uv/install.sh | sh || { echo " Setup failed."; read -r; exit 1; }
    export PATH="$HOME/.local/bin:$PATH"
  fi
  uv venv --python 3.11 .venv && \
  uv pip install --python .venv/bin/python -r requirements.txt -e . && \
  .venv/bin/python scripts/setup_models.py || { echo " Setup stopped with an error (see above)."; read -r; exit 1; }
  .venv/bin/python scripts/prepare_resources.py
  .venv/bin/python scripts/build_registry.py
  echo " Setup finished."
fi

echo
echo " Starting BlueSight. Your browser opens at http://localhost:8501"
echo " Keep this window open while you use BlueSight. Close it to stop."
(sleep 6 && open "http://localhost:8501") &
exec .venv/bin/python -m streamlit run app/streamlit_app.py
