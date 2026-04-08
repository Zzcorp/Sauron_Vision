#!/usr/bin/env python
"""
set_default_pin.py
Sets PIN "0000" for every user that doesn't have one yet.
Run from project root (next to manage.py):

    python set_default_pin.py

On Render: open the Shell tab and run the same command.
Safe to re-run — only touches users with an empty PIN.
"""
import os, sys, django
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from django.contrib.auth.models import User
from django.contrib.auth.hashers import make_password
from portfolio.trader_profile import TraderProfile

DEFAULT_PIN = "0000"
hashed = make_password(DEFAULT_PIN)

updated = created = skipped = 0
for u in User.objects.all():
    prof, was_created = TraderProfile.objects.get_or_create(user=u)
    if was_created:
        created += 1
    if prof.access_pin_hash:
        skipped += 1
        continue
    prof.access_pin_hash = hashed
    prof.save(update_fields=["access_pin_hash"])
    updated += 1
    print(f"  ✓ {u.username}  →  PIN {DEFAULT_PIN}")

print(f"\nDone. updated={updated}  profiles_created={created}  already_had_pin={skipped}")
print(f"Default PIN is {DEFAULT_PIN}. Tell your users to change it after first login.")