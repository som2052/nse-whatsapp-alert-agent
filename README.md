# 🔔 NSE WhatsApp Alert Agent

Real-time WhatsApp alerts for NSE (National Stock Exchange of India) corporate filings and announcements — built for SME investors.

## What It Does

```
NSE India ──poll──▶ Alert Agent ──filter──▶ Summarize ──send──▶ WhatsApp
(every 2 min)       (your watchlist)       (AI/rules)          (+91-8951308984)
```

- **Monitors** NSE corporate filings for your watchlist companies
- **Deduplicates** alerts so you never get the same announcement twice
- **Summarizes** announcements with AI (Claude) or rule-based extraction
- **Sends** formatted WhatsApp messages with priority tags (🔴 HIGH / 🟡 MEDIUM / 🟢 LOW)
- **Tracks** all sent alerts in a local SQLite database

## Quick Start (5 minutes)

### Step 1: Install Dependencies

```bash
cd ~/nse-whatsapp-alert-agent
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### Step 2: Set Up Twilio WhatsApp

1. **Create a free Twilio account**: https://www.twilio.com/try-twilio
2. **Enable WhatsApp Sandbox**: https://console.twilio.com/us1/develop/sms/try-it-out/whatsapp-learn
3. **Join the sandbox**: Send the join message (e.g., `join candy-example`) from your WhatsApp (+91-8951308984) to the Twilio WhatsApp number shown on the sandbox page
4. **Copy your credentials** from the Twilio Console

### Step 3: Configure Environment

```bash
cp .env.example .env
```

Edit `.env` with your credentials:

```env
TWILIO_ACCOUNT_SID=ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TWILIO_AUTH_TOKEN=your_auth_token_here
TWILIO_WHATSAPP_FROM=whatsapp:+14155238886
WHATSAPP_TO=whatsapp:+918217613997
POLL_INTERVAL_SECONDS=120

# Optional: Add for AI-powered summaries
ANTHROPIC_API_KEY=sk-ant-xxxxx
```

### Step 4: Add Your Companies

Edit `companies.json` to add your SME watchlist:

```json
{
  "watchlist": [
    { "symbol": "RELIANCE", "name": "Reliance Industries Limited" },
    { "symbol": "TCS", "name": "Tata Consultancy Services Limited" },
    { "symbol": "INFY", "name": "Infosys Limited" }
  ]
}
```

> 💡 Find exact NSE symbols at: https://www.nseindia.com/market-data/securities-available-for-trading

### Step 5: Test & Run

```bash
# Test WhatsApp connection
python agent.py --test

# Run one check cycle
python agent.py --once

# Start continuous monitoring (Ctrl+C to stop)
python agent.py
```

## Usage

```bash
python agent.py               # Start continuous monitoring
python agent.py --test        # Send a test WhatsApp message
python agent.py --once        # Run one check and exit
python agent.py --status      # Show status and recent alerts
```

## Sample WhatsApp Alert

```
🔔 *NSE ALERT*
━━━━━━━━━━━━━━━━━━━━━
🏢 *Reliance Industries Ltd* (RELIANCE)
📅 23-May-2026

📋 *Subject:*
Board Meeting Intimation for Consideration of
Financial Results for Q4 FY2026 and Dividend

🤖 *AI Summary:*
Significance: 🔴 HIGH
Reliance has scheduled a board meeting to review
Q4 FY2026 financial results and consider dividend
declaration. This is significant for investors as
it may impact stock price based on earnings
performance and dividend payout.

📎 *Document:*
https://www.nseindia.com/corporate/...

━━━━━━━━━━━━━━━━━━━━━
🔗 View on NSE: https://www.nseindia.com/companies-listing/corporate-filings-announcements
```

## Run as Background Service (Linux/Mac)

### Using nohup (simple)

```bash
nohup python agent.py > /dev/null 2>&1 &
echo $! > agent.pid
```

To stop:
```bash
kill $(cat agent.pid)
```

### Using systemd (Linux - recommended for production)

```ini
# /etc/systemd/system/nse-alert.service
[Unit]
Description=NSE WhatsApp Alert Agent
After=network.target

[Service]
Type=simple
User=your_username
WorkingDirectory=/home/your_username/nse-whatsapp-alert-agent
ExecStart=/home/your_username/nse-whatsapp-alert-agent/venv/bin/python agent.py
Restart=always
RestartSec=30

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable nse-alert
sudo systemctl start nse-alert
sudo systemctl status nse-alert    # Check status
journalctl -u nse-alert -f         # View logs
```

### Using launchd (macOS - recommended)

```xml
<!-- ~/Library/LaunchAgents/com.nse.alert.plist -->
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.nse.alert</string>
    <key>ProgramArguments</key>
    <array>
        <string>/Users/s0d0g3e/nse-whatsapp-alert-agent/venv/bin/python</string>
        <string>/Users/s0d0g3e/nse-whatsapp-alert-agent/agent.py</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>/Users/s0d0g3e/nse-whatsapp-alert-agent/agent.log</string>
    <key>StandardErrorPath</key>
    <string>/Users/s0d0g3e/nse-whatsapp-alert-agent/agent_error.log</string>
</dict>
</plist>
```

```bash
launchctl load ~/Library/LaunchAgents/com.nse.alert.plist
launchctl start com.nse.alert
```

## Project Structure

```
nse-whatsapp-alert-agent/
├── agent.py           # Main orchestrator (run this)
├── nse_scraper.py     # NSE API client with session management
├── whatsapp_sender.py # Twilio WhatsApp integration
├── summarizer.py      # AI + rule-based summarization
├── db.py              # SQLite dedup tracking
├── companies.json     # Your watchlist (edit this)
├── .env               # Your credentials (create from .env.example)
├── .env.example       # Template for credentials
├── requirements.txt   # Python dependencies
├── .gitignore         # Git ignore rules
└── README.md          # This file
```

## Important Notes

### Twilio WhatsApp Sandbox Limitations
- Sandbox sessions expire after **72 hours** of inactivity
- You must re-join the sandbox if it expires (send the `join` keyword again)
- For production use, apply for a **WhatsApp Business Profile** through Twilio (~$0.005/message)

### NSE Rate Limits
- The agent uses session management and rate limiting to avoid IP blocks
- Default poll interval is 2 minutes — don't reduce below 60 seconds
- NSE sessions expire; the agent handles automatic re-authentication

### Cost Estimates
- **Twilio WhatsApp Sandbox**: Free (limited to sandbox participants)
- **Twilio WhatsApp Business**: ~₹0.40/message (~$0.005)
- **Anthropic Claude API** (optional): ~₹1-2 per summary (~$0.01-0.02)
- **Running cost**: For 10 companies with ~5 announcements/day ≈ ₹100-200/month

## Troubleshooting

| Issue | Solution |
|-------|----------|
| No messages received | Re-join Twilio WhatsApp sandbox |
| NSE returns empty | NSE may be blocking; wait 5 min and retry |
| `401 Unauthorized` | Session expired; agent auto-refreshes |
| Import errors | Run `pip install -r requirements.txt` |
| No announcements | Check if your companies have filings today |
