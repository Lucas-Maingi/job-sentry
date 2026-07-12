# Deploying JobSentry 24/7 on an Oracle Cloud Always-Free VM

This runs JobSentry (the autonomous scanner + dashboard) on a **genuinely free,
always-on** server so it hunts and triages jobs around the clock — without your
laptop needing to be on. Oracle's Always-Free tier is a real perpetual VM, not a
trial. Budget: **$0/month** within the free shapes.

> Scope: this is a **single-user** deployment ("for me"). See the Security section
> before exposing the dashboard to the public internet — Streamlit has no built-in
> login.

## What you'll need
- An Oracle Cloud account (free; a card is required for identity verification only).
- ~30 minutes.
- Your Serper + Groq API keys (both free).

---

## 1. Create the VM
1. Sign up at **cloud.oracle.com** and finish identity verification.
2. Console → **Compute → Instances → Create Instance**.
3. Image & shape: choose **Canonical Ubuntu 22.04**, and for shape pick an
   **Always Free-eligible** one — either `VM.Standard.E2.1.Micro` (x86) or, for
   more headroom, `VM.Standard.A1.Flex` (Ampere ARM) with **1–2 OCPUs / 6–12 GB
   RAM** (still inside the Always-Free allowance).
4. Add your **SSH public key** (or let Oracle generate a keypair and download it).
5. Create. Note the instance's **public IP**.

## 2. Open the ports
In the instance's **VCN → Security List** (or a Network Security Group), add
**ingress** rules:
- TCP **8501** (the dashboard) — **source: your home IP only** (recommended), or
  `0.0.0.0/0` only if you add auth (Security section).
- TCP **8000** (the API) — you generally do **not** need this open publicly.
- (SSH TCP 22 is open by default.)

Ubuntu also has its own firewall; open the port there too:
```bash
sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 8501 -j ACCEPT
sudo netfilter-persistent save
```

## 3. Install Docker
```bash
ssh ubuntu@YOUR_PUBLIC_IP
sudo apt-get update && sudo apt-get install -y docker.io docker-compose-plugin git
sudo usermod -aG docker $USER && newgrp docker
```

## 4. Deploy JobSentry
```bash
git clone https://github.com/Lucas-Maingi/job-sentry.git
cd job-sentry

# Create the secrets file from the template and paste in your keys
cp .env.prod.example .env
nano .env          # fill JOBSENTRY_SERPER_API_KEY and JOBSENTRY_LLM_API_KEY

# Build and start (runs detached; restarts on reboot)
docker compose -f docker-compose.prod.yml up -d --build
```
First build takes a few minutes (it installs a headless browser for the
apply step). Then:
- Dashboard: **http://YOUR_PUBLIC_IP:8501**
- The **autonomous scanner is now running** — every `JOBSENTRY_AUTO_SCAN_INTERVAL_MINUTES`
  it re-scans every profile you've created, applies your location/experience/salary
  filters, scores matches, and drafts cover letters. Your laptop can be off.

Create your profile in the dashboard (name, email, **paste your resume**, set your
filters), and it starts working.

## 5. Everyday operations
```bash
docker compose -f docker-compose.prod.yml logs -f     # watch the scanner
docker compose -f docker-compose.prod.yml restart      # restart
git pull && docker compose -f docker-compose.prod.yml up -d --build   # update
```
Your data (DB, uploaded resumes, screenshots) lives in the `jobsentry-data`
Docker volume and survives rebuilds and reboots.

---

## Security — read before exposing the dashboard
Streamlit has **no login**. Anyone who can reach port 8501 can see your pipeline.
Pick one:

1. **Simplest — restrict by IP (recommended for "just me"):** in the Oracle
   Security List, set the 8501 ingress source to **your home IP** (`x.x.x.x/32`)
   instead of `0.0.0.0/0`. Nobody else can reach it.
2. **SSH tunnel (most private):** don't open 8501 publicly at all. From your
   laptop: `ssh -L 8501:localhost:8501 ubuntu@YOUR_PUBLIC_IP`, then open
   `http://localhost:8501`. The dashboard is only reachable through your SSH session.
3. **Public with a password:** put **nginx** in front with HTTP Basic Auth (and a
   free Let's Encrypt cert if you point a domain at it). More setup; only needed if
   you want to reach it from anywhere without SSH.

Also: your `.env` holds real API keys — it's gitignored, keep it that way, and
never paste it anywhere.

## A note on "scraping the whole web"
JobSentry finds listings through the **Serper (Google Search) API** — it surfaces
what Google indexes for your queries across job boards, which is broad but not a
bespoke crawler hitting every ATS directly. The filters then keep only what fits
your location/experience/salary constraints. It's an aggregator + triage engine,
not a full-internet spider.
