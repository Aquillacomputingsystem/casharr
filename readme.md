# 💰 Casharr — Automated Discord & Plex Subscription Manager

<p align="center">
  <img src="./assets/casharr_logo_white.png" alt="Casharr Logo" width="220"/>
</p>

<h2 align="center">💰 Casharr — Automated Discord & Plex Subscription Manager</h2>

<p align="center">
  <b>Casharr</b> is a full-stack automation system that manages subscriptions, trials, payments, and Plex access for Discord communities.<br>
  Powered by <b>Flask</b>, <b>Discord.py</b>, and <b>PayPal IPN</b> — all wrapped in a clean ARR-style WebUI. **NOTE I AM NOT A PROGRAMMER. I HAVE MADE THIS ENTIRELY WITH AI AND FRANKLY MAY EXPLODE AT ANY MOMENT, YOU HAVE BEEN WARNED, IF YOU FIND ISSUES, FLAG THEM AND ILL USE AI TO FIX IT**
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.11-blue" alt="Python 3.11"/>
  <img src="https://img.shields.io/badge/Framework-Flask-orange" alt="Flask"/>
  <img src="https://img.shields.io/badge/Discord-Bot-blueviolet" alt="Discord"/>
  <img src="https://img.shields.io/badge/License-MIT-green" alt="License MIT"/>
</p>

---

## 🚀 Overview

**Casharr** automates your entire subscription lifecycle for Plex and Discord — including:

- 🧾 **PayPal payments** (via IPN verification)
- 🎟️ **Trial tracking & reminders**
- 🤖 **Discord roles & automation**
- 🎬 **Plex access control**
- 💌 **Promotions, referrals & renewals**
- 🧠 **Configurable WebUI for admins**

It’s designed to run unattended — everything from invite to renewal happens automatically.

---

## 🖥️ WebUI Dashboard

Casharr includes a fully interactive **ARR-style WebUI**, built in Flask.

### ✨ Features
- **Dashboard:** Live stats for members, trials, payers, expired users, and service connections (Discord + Plex).  
- **Members Page:** View, edit, and delete members dynamically via API.  
- **Reports:** Generate PDF/XML summaries for admins.  
- **Config Pages:** Edit all bot, PayPal, and Plex settings directly through the browser.  
- **System Tools:** Logs, backups, restore, updates, and events viewer.  
- **Authentication:** Optional WebUI login or Discord OAuth2 (future phase).

### 🧩 Example Sections
```
Dashboard  — Member stats + Service status  
Members    — CRUD table linked to SQLite  
Reports    — Export usage, payments, and referral summaries  
Config     — Discord / PayPal / Plex / Reminders / Settings  
System     — Logs / Tasks / Backups / Updates / Events
```

---

## 🧠 How It Works -

### 1️⃣ Join & Onboarding
When a new member joins the Discord server:
- Casharr assigns the **Initial** role.
- Sends a DM with onboarding instructions.
- Starts their **Trial** timer.
- Optionally invites them to Plex.

If they joined via a referral, the bot automatically links them to the referrer — no manual setup.

---

### 2️⃣ Trial Period
- Members keep **Trial** access for the configured number of days.  
- Before expiry, they receive a DM reminder.  
- If no payment is made, the bot removes roles and Plex access.  
- Admins are notified of all expirations automatically.

---

### 3️⃣ Payment & Auto-Upgrade
When a member pays via **PayPal**:
- The **IPN server** validates the transaction.  
- Casharr:
  - Extends their expiry date.
  - Grants the **Payer** role.
  - Updates the database.
  - Logs the renewal and notifies admins.

All handled instantly and securely.

---

### 4️⃣ Referral Rewards
Members can generate personal invite links using `/referral_link`.  
When someone joins with that link:
- The referrer is recorded.
- When the new user pays, the referrer earns bonus days automatically.

| Friend’s Plan | Referrer Bonus |
|---------------|----------------|
| 1 Month | +7 days |
| 3 Months | +14 days |
| 6 Months | +30 days |
| 12 Months | +60 days |

Referrals stack with promo codes for maximum reward flexibility.

---

### 5️⃣ Promotions & Discounts
Define `[Promo]` rules in `config.ini` — Casharr:
- Detects eligible users.
- Applies discounted rates at checkout.
- Marks promotions as used after redemption.

---

### 6️⃣ Ongoing Automation
Casharr runs background loops for:
- **Enforce Access** — ensures only active members have roles.
- **Audit Plex** — verifies active Plex invites.
- **Reminders** — renewal alerts via DM.
- **Reports** — PDF and XML generation for admins.

---

## ⚙️ Configuration

Casharr uses an easy `.ini` configuration format:
```ini
[Discord]
Token = your_bot_token_here
AdminRole = Admin
TrialRole = Trial
PayerRole = Payer
LifetimeRole = Lifetime

[PayPal]
ReceiverEmail = you@example.com
IPN_URL = https://yourdomain.com/ipn

[Plex]
URL = http://192.168.1.237:32400
Token = YOUR_PLEX_TOKEN

[Payments]
DefaultCurrency = AUD
1Month = 10
3Month = 25
6Month = 50
12Month = 90
```

---

## 🧰 System Pages

| Section | Description |
|----------|--------------|
| 🧾 **Logs** | View rotating log files directly in the WebUI. |
| 💾 **Backups** | Create, restore, or upload SQLite backups. |
| 🔔 **Events** | Real-time system event viewer. |
| ⚙️ **Tasks** | Background job control (reminders, audit, enforce). |
| 🧱 **Updates** | Checks GitHub releases and compares versions. |

---

## 🧩 Upcoming Features

- 🔐 Discord OAuth2 login  
- 📊 Analytics dashboard (referrals, payments, trials)  
- 🧾 PDF invoice generation  
- 📨 SMTP alerts and summaries  
- 🔍 WebUI filters and search  
- 🔁 Task scheduler controls  
- 🧰 Maintenance and cleanup tools  
- 💸 Stripe payment integration  

---

## 🧱 Installation

```bash
git clone https://github.com/yourusername/casharr.git
cd casharr
pip install -r requirements.txt
python run.py
```

Then open [http://localhost:5000](http://localhost:5000) in your browser.

For Docker users:
```bash
docker build -t casharr .
docker run -p 5000:5000 casharr
```

---

## 🧾 Roles Overview

| Stage | Role | Description |
|--------|------|-------------|
| New Join | `Initial` | Member joins server, setup begins |
| Trial | `Trial` | Active free access |
| Subscriber | `Payer` | Payment confirmed |
| Permanent | `Lifetime` | Lifetime role (never expires) |
| Management | `Admin` | Full system control |

---

## 🧩 License
Licensed under the [MIT License](./LICENSE).  
© 2025 Aquilla Computing System — Casharr Project.

---

## 📬 Contact
- Discord: [YourServerInviteHere]
- GitHub: [github.com/yourusername/casharr](https://github.com/yourusername/casharr)
- Website: Coming Soon

---

_Last updated: 2025-10-31_
