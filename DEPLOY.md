# Deploying Sauron Vision

**The deployment authority is [`deploy/RUNBOOK.md`](deploy/RUNBOOK.md).**
Read it before touching the live box — it carries the non-obvious parts:
the mandatory `--env-file` shape (or the `./deploy/dc` wrapper that types
it for you), the one-shot `migrate` service, the master switch every
component ships OFF behind, and the backup sidecar's rclone requirement.

The stack is one file: `deploy/docker-compose.yml` (+ `deploy/Caddyfile`).
Updating a running deployment is:

```bash
git pull
./deploy/dc up -d --build
./deploy/dc logs -f migrate   # must exit 0
```

Retiring a broker has its own document: **[`deploy/IBKR_RETIREMENT.md`](deploy/IBKR_RETIREMENT.md)**
— the staged plan for taking IBKR out, in the order that keeps the platform
able to SEE an account it can no longer trade. Read its first rule before
running any of it.

A defect that is deliberately NOT being fixed has one too:
**[`deploy/FOLLOW_DENOMINATOR.md`](deploy/FOLLOW_DENOMINATOR.md)** — why the
share a following pool takes is computed over a denominator that counts pools
the sync then refuses, why every way of correcting that arithmetic is worse
than the error (one doubles a live pool, one splits the book, one disarms the
drawdown de-risk), and what was fixed instead. Read it before touching
`allocate_shares` or `followers_of`.

This file used to be a Render.com blueprint guide. That era is over — the
platform runs on a single VPS from the compose stack above, and a second
deployment document disagreeing with the runbook was worth more as a bug
than as a backup. (`render.yaml`-era assumptions live on only in git
history.)
