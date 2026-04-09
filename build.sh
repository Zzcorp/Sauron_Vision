#!/usr/bin/env bash
set -o errexit
echo "SAURON VISION — Build starting..."

# Use Render's pip cache directory for faster installs
export PIP_CACHE_DIR="${XDG_CACHE_HOME:-/opt/render/.cache}/pip"
mkdir -p "$PIP_CACHE_DIR"

pip install --upgrade pip setuptools wheel 2>&1 | tail -1

# --prefer-binary avoids compiling C extensions from source
# --cache-dir reuses wheels across deploys
pip install --prefer-binary --cache-dir "$PIP_CACHE_DIR" -r requirements.txt 2>&1 | tail -5

python manage.py collectstatic --no-input 2>&1 | tail -1
python manage.py migrate --no-input 2>&1 | tail -3

# Seed data on first deploy (idempotent — skips existing rows)
python manage.py seed_instruments 2>/dev/null || true
python manage.py seed_components 2>/dev/null || true

# Seed market configs
python -c "
import django, os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()
from core.market_config import seed_market_configs
print(f'Markets: {seed_market_configs()} new')
" 2>/dev/null || true

echo "SAURON VISION — Build complete!"
