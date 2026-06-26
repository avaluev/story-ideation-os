# OpenRouter API Key — Setup Guide for Investors

OpenRouter is a single billing account that gives access to dozens of AI models — Anthropic Claude, OpenAI GPT, Google Gemini, Meta Llama, and others — through one API key. Anomaly Engine uses OpenRouter to run its 10-phase pipeline. Setup takes about 10 minutes and costs about $20 to start (covers 1–3 full concept runs).

## Why OpenRouter and not OpenAI directly?

Anomaly Engine uses multiple models (Claude Sonnet 4.6 for drafting, Perplexity Sonar for research, Llama for parallel work). OpenRouter is the one billing account that covers all of them. It's a pass-through service — OpenRouter charges you the same per-token price as the model provider, plus a small platform fee. The convenience of one key beats managing five separate accounts.

## Step 1 — Create your account

1. Go to [https://openrouter.ai/](https://openrouter.ai/)
2. Click "Sign In" (top-right). You can sign in with Google, GitHub, or email.
3. On first sign-in, you'll be asked your name and use-case. Choose "Research" or "Building an internal tool".
4. *When you see your name in the top-right corner instead of "Sign In", you're logged in.*

## Step 2 — Add a payment method

1. Click your profile icon (top-right) → "Settings" → "Credits" (left sidebar).
2. Click "Add Payment Method". OpenRouter accepts Visa, Mastercard, American Express, and cryptocurrencies (USDC, BTC, ETH).
3. Enter your card details. (Stripe is the payment processor; OpenRouter never sees the card number.)
4. *Note: Credit-card top-ups are instant. Crypto can take 10 minutes to confirm.*

## Step 3 — Top up your balance

1. On the same Credits page, find the "Add Credits" box.
2. **Recommended starter amount: $20.** This covers approximately 1–3 full concept generation runs (each costs $4–18 depending on theme complexity).
3. Click "Add Credits" → confirm.
4. You should see your balance update to $20 within seconds.
5. *Tip: OpenRouter does NOT auto-renew. You add funds manually when you want more. No subscription, no surprise charges.*

## Step 4 — Create an API key

1. Navigate to [https://openrouter.ai/settings/keys](https://openrouter.ai/settings/keys) (or Settings → "API Keys" in the left sidebar).
2. Click "Create Key".
3. **Name:** type `anomaly-engine` (this helps you identify the key later).
4. **Credit limit (optional but recommended):** set to `$50`. This caps how much the key can spend total. If the platform ever runs wild, $50 is the maximum loss.
5. Click "Create".
6. **CRITICAL: The key is shown ONCE.** It starts with `sk-or-v1-`. Copy it immediately to a safe place (e.g., Apple Notes, 1Password). If you close the dialog without copying, you'll need to create a new key.

## Step 5 — Hand the key to Claude Code

1. When Claude Code (running the master prompt) asks "Please paste your OpenRouter API key:", paste the key (Cmd+V) into the chat input and press Enter.
2. Claude Code writes the key into a local file at `~/anomaly-engine-investor-v1/.env`. This file lives on YOUR Mac only — it is never uploaded, synced, or sent anywhere except to OpenRouter when the pipeline runs.
3. The file has Unix permission `600` (only you can read it).

## Monitoring your spend

At any time, visit [https://openrouter.ai/activity](https://openrouter.ai/activity) to see every API call, its cost, and which model was used. The Credits page ([https://openrouter.ai/settings/credits](https://openrouter.ai/settings/credits)) shows your remaining balance. You can set up email alerts at "Settings → Notifications" to receive a message when balance drops below a threshold (e.g., $5).

## Free models (optional)

OpenRouter offers some free models (rate limit: 50 calls/day per key). Anomaly Engine uses these for low-stakes parallel work to save your paid budget. You don't need to configure anything — the system uses free models automatically when available.

## Common questions

**Q: What if my key gets exposed?**

A: Go to [https://openrouter.ai/settings/keys](https://openrouter.ai/settings/keys), click the trash icon next to the compromised key. Create a new one. Re-run the bootstrap step in Claude Code to update the local file.

**Q: How much does a full run cost?**

A: Usually $4 to $18 depending on theme complexity and how many amplification passes the pipeline decides to run. The system caps itself at the "weekly token budgets" defined in `.env` (defaults: 2M Opus, 20M Sonnet, 100M Haiku tokens per week).

**Q: Can I use OpenAI's key instead?**

A: No — Anomaly Engine routes all calls through OpenRouter for budget consolidation. OpenAI doesn't sell Claude tokens. Stick with one OpenRouter key.

**Q: What happens if I run out of credits mid-run?**

A: The pipeline pauses and writes a partial result. You add credits and resume with `make single THEME="..." RESUME=1` (Claude Code will guide you).

## Security checklist

- Never paste your API key into a website, email, or chat other than Claude Code on your own Mac.
- Never commit the key to a git repository (the platform's `.gitignore` already excludes `.env`).
- If you suspect your key was exposed, rotate it within 5 minutes at [https://openrouter.ai/settings/keys](https://openrouter.ai/settings/keys).
- Use a per-project key (named "anomaly-engine") — not your master key.
