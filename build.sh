#!/usr/bin/env bash
set -o errexit
echo "SAURON VISION — Build starting..."

pip install --upgrade pip
pip install -r requirements.txt

python manage.py collectstatic --no-input
python manage.py migrate --no-input

# Seed data on first deploy
python manage.py seed_instruments 2>/dev/null || true
python manage.py seed_components 2>/dev/null || true

# Seed market configs
python -c "
import django; import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()
from core.market_config import seed_market_configs
print(f'Markets: {seed_market_configs()} new')
" 2>/dev/null || true

echo "SAURON VISION — Build complete!"
