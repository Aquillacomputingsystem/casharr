<p align="left">
  <img src="./assets/casharr_logo_white.png" alt="Casharr Logo" width="150"/>
</p>

# 🧾 Configuration Guide

Edit `config/config.ini` to customize your environment.

## Discord Settings
```ini
[Discord]
BotToken = YOUR_DISCORD_BOT_TOKEN
InitialRole = No Access
TrialRole = Trial
PayerRole = Payer
LifetimeRole = Lifetime
AdminRole = Admin
AdminChannelID = 123456789012345678
```
## PayPal Settings
```ini
[PayPal]
Mode = live
BusinessEmail = you@example.com
IPN_URL = https://yourdomain.com/paypal/ipn
PaymentBaseLink = https://www.paypal.com/paypalme/yourusername
```
