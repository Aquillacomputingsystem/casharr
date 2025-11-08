# 🧭 Casharr Development Roadmap
> A complete feature and milestone guide for the Casharr subscription management system.

---

## 📌 Overview
Casharr integrates **Discord**, **PayPal**, and **Plex** into a single automation ecosystem for managing subscriptions, referrals, and reminders.  
This roadmap tracks all major development phases — from the core WebUI to advanced analytics, automation, and multi-service expansion.

---

## ✅ Phase 1 — Core Functionality (Completed)
**Goal:** Build a stable, fully functional system for member management, payments, and configuration.

| Feature | Description | Status |
|----------|--------------|--------|
| 🎨 WebUI ARR-style dashboard | Responsive ARR-inspired interface using Flask templates and CSS grid. | ✅ |
| 💳 PayPal IPN integration | Verify payments, update database, trigger reminders. | ✅ |
| 🤖 Discord bot | Handles trials, roles, promotions, referrals. | ✅ |
| 🎬 Plex integration | Invite/remove members, enforce access roles. | ✅ |
| 🧩 Config pages | Manage Discord, Payments, Plex, Reminders, Settings. | ✅ |
| 📁 System tools | Logs, backups, restore, updates. | ✅ |
| 🔐 Basic WebUI login | SHA-256 authentication via `[WebUI]` section. | ✅ |
| 🗃 Database auto-migration | Create and update missing columns. | ✅ |
| 📊 Dashboard metrics | Show member counts, trials, payers, expired. | ✅ |
| 📜 Reports system | Generate PDF/XML summaries. | ✅ |
| 📨 Reminder automation | Send DM reminders and expiry alerts. | ✅ |
| 🧾 Referral & promo system | Track referrers and apply discounts. | ✅ |

**Result:**  
Casharr WebUI and backend are 100% functional — stable base for expansion.

---

## ⚙️ Phase 2 — Reliability & Administration
**Goal:** Improve resilience, add maintenance and monitoring utilities.

| Feature | Description | Status |
|----------|--------------|--------|
| 💾 **Database Migration Utility** | Add version table and schema upgrade mechanism. | ☐ |
| 🧰 **Maintenance Tools** | Cleanup expired data, compact DB, export logs. | ☐ |
| 🧱 **Auto log retention** | Rotate and purge old logs based on `[Logging] RetentionDays`. | ☐ |
| 🔄 **Backup scheduling** | Automated daily/weekly backup tasks. | ☐ |
| 🧾 **Daily summaries** | Email or Discord message summarizing daily stats/errors. | ☐ |
| 📬 **Email notifications (SMTP)** | Send error or backup notifications to admin. | ☐ |
| 🪄 **System health banner** | Show global status (Discord/Plex offline warnings). | ☐ |

---

## 📊 Phase 3 — Analytics & Insights
**Goal:** Provide data visualization and deeper operational awareness.

| Feature | Description | Status |
|----------|--------------|--------|
| 📈 **Analytics dashboard** | New page with charts for members, payments, referrals. | ☐ |
| 📅 **Historical reports** | Store monthly summaries in DB, generate graphs. | ☐ |
| 🧩 **Advanced filtering** | Filter/search members by role, expiry, referrer. | ☐ |
| 🔍 **Search bar (Members)** | Live text search via `/api/members` filters. | ☐ |
| 📉 **Churn tracking** | Track expired vs renewed members. | ☐ |
| 💬 **Activity timeline** | Visualize joins, renewals, payments, removals. | ☐ |

---

## 🤖 Phase 4 — Automation & Monetization
**Goal:** Improve payment, scheduling, and professional features.

| Feature | Description | Status |
|----------|--------------|--------|
| 🔁 **Scheduler management page** | Start/stop background tasks from WebUI. | ☐ |
| 🧾 **PDF invoices/receipts** | Auto-generate and email invoices on payment. | ☐ |
| 📦 **Referral reward options** | Allow choice of bonus days, credits, or discounts. | ☐ |
| 💸 **Stripe integration** | Add alternative card payment processor. | ☐ |
| 💰 **Promo scheduling** | Automatically start/stop promo events. | ☐ |
| ⏰ **Task timeline** | Show “last run” and “next run” per scheduler. | ☐ |
| 🧩 **Webhook integration** | Push events to Discord or external webhooks (Tautulli, Plex, etc.). | ☐ |

---

## 🔐 Phase 5 — Security & Access Control
**Goal:** Harden authentication and support multi-admin use.

| Feature | Description | Status |
|----------|--------------|--------|
| 🧍‍♂️ **Discord OAuth2 login** | Replace static login with Discord SSO. | ☐ |
| 🧑‍💻 **Multi-admin roles** | Add role-based access (Owner, Manager, Viewer). | ☐ |
| 🔑 **2FA support** | Optional TOTP authentication for admin accounts. | ☐ |
| 🧾 **Session logging** | Track login history and active sessions. | ☐ |
| 🔒 **API key system** | Secure external automation or CLI integration. | ☐ |
| 🧠 **Rate-limit & CSRF protection** | Harden Flask endpoints for production. | ☐ |

---

## 🌐 Phase 6 — Integrations & Multi-Service Expansion
**Goal:** Broaden ecosystem support and compatibility.

| Feature | Description | Status |
|----------|--------------|--------|
| 🎬 **Multi-Plex support** | Manage multiple Plex servers. | ☐ |
| 🧩 **Jellyfin / Emby integration** | Extend to alternative media servers. | ☐ |
| 📡 **ARR ecosystem link** | Integrate Sonarr/Radarr for missing media reporting. | ☐ |
| 🤝 **Webhook analytics** | Track webhook deliveries and failures. | ☐ |
| 🧭 **External API** | REST API for integration with dashboards or third-party tools. | ☐ |
| ⚙️ **Docker production build** | Add Gunicorn/Nginx and auto-update mechanism. | ☐ |

---

## 🧠 Phase 7 — Intelligence & Smart Automation
**Goal:** Add AI-powered analysis and predictive automation.

| Feature | Description | Status |
|----------|--------------|--------|
| 🧮 **Predictive renewal analysis** | Estimate likely renewals or cancellations. | ☐ |
| 🔍 **Auto-categorized events** | Classify log events (errors, payments, trials). | ☐ |
| 💬 **AI assistant (optional)** | Integrate with Ollama/Open-WebUI for admin support. | ☐ |
| 🧰 **Smart fixes** | Suggest configuration fixes when common errors occur. | ☐ |

---

## 🧩 Phase 8 — UX & Polish
**Goal:** Refine user experience, mobile support, and customization.

| Feature | Description | Status |
|----------|--------------|--------|
| 📱 **Mobile-friendly layout** | Collapsible sidebar, responsive dashboard. | ☐ |
| 🎨 **Custom theme editor** | User-selectable color themes & accent colors. | ☐ |
| 🌙 **Dark/light mode persistence** | Already implemented — refine icons/text contrast. | ✅ |
| 🔔 **Inline notifications** | Real-time toast alerts for events or updates. | ☐ |
| 🧩 **Localization** | Support multiple languages. | ☐ |

---

## 📘 Phase 9 — Long-Term Evolution
**Goal:** Build Casharr into a platform-level service.

| Feature | Description | Status |
|----------|--------------|--------|
| 🧩 **Plugin architecture** | `/plugins/` directory for community extensions. | ☐ |
| 🧠 **Machine learning recommendations** | Predict optimal promo pricing, message timing. | ☐ |
| 🧾 **Multi-tenant hosting** | Manage multiple servers/accounts in one dashboard. | ☐ |
| 📦 **Enterprise deployment** | CI/CD integration, scaling, API gateway. | ☐ |

---

## 🏁 Version Targets

| Version | Phase | Milestone |
|----------|--------|-----------|
| **v1.0.0** | Phase 1 | Core release (✅ Completed) |
| **v1.1.0** | Phase 2 | Stability & maintenance |
| **v1.2.0** | Phase 3 | Analytics & insights |
| **v1.3.0** | Phase 4 | Automation & monetization |
| **v1.4.0** | Phase 5 | Security overhaul |
| **v2.0.0** | Phase 6+ | Multi-service & AI expansion |

---

## 💬 Notes
- Each feature uses `[x]` for completion tracking once implemented.  
- Keep commits grouped by phase (e.g., `phase2/maintenance-tools` branch).  
- Use `CHANGELOG.md` for per-release notes.  
- Update this roadmap as new ideas evolve.

---

**Last Updated:** {{CURRENT_DATE}}  
**Maintainer:** [@Aquillacomputingsystem]  
**Project:** [Casharr — Subscription Automation Suite](https://github.com/Aquillacomputingsystem/casharr)
