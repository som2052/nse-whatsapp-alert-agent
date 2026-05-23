"""
WhatsApp Message Sender via Twilio
====================================
Sends formatted WhatsApp messages using Twilio's WhatsApp Business API.
Supports both sandbox (testing) and production modes.
"""

import logging
from twilio.rest import Client
from twilio.base.exceptions import TwilioRestException

logger = logging.getLogger(__name__)


class WhatsAppSender:
    """
    Sends WhatsApp messages via Twilio API.

    Setup:
    1. Create a Twilio account at https://www.twilio.com
    2. Enable WhatsApp Sandbox at https://console.twilio.com/us1/develop/sms/try-it-out/whatsapp-learn
    3. Join the sandbox by sending "join <your-sandbox-keyword>" to the Twilio WhatsApp number
    4. For production: Apply for a WhatsApp Business Profile via Twilio
    """

    # WhatsApp message length limit
    MAX_MESSAGE_LENGTH = 4096

    def __init__(self, account_sid: str, auth_token: str, from_number: str, to_number: str):
        """
        Initialize WhatsApp sender.

        Args:
            account_sid: Twilio Account SID
            auth_token: Twilio Auth Token
            from_number: Twilio WhatsApp number (format: whatsapp:+14155238886)
            to_number: Recipient WhatsApp number (format: whatsapp:+918217613997)
        """
        self.client = Client(account_sid, auth_token)
        self.from_number = from_number
        self.to_number = to_number

        # Validate number format
        if not from_number.startswith("whatsapp:"):
            self.from_number = f"whatsapp:{from_number}"
        if not to_number.startswith("whatsapp:"):
            self.to_number = f"whatsapp:{to_number}"

        logger.info(f"📱 WhatsApp sender initialized: {self.from_number} → {self.to_number}")

    def send_message(self, body: str) -> bool:
        """
        Send a WhatsApp message.

        Args:
            body: Message text (max 4096 characters)

        Returns:
            True if sent successfully, False otherwise
        """
        if len(body) > self.MAX_MESSAGE_LENGTH:
            logger.warning(f"⚠️ Message truncated from {len(body)} to {self.MAX_MESSAGE_LENGTH} chars")
            body = body[:self.MAX_MESSAGE_LENGTH - 50] + "\n\n... [Message truncated]"

        try:
            message = self.client.messages.create(
                body=body,
                from_=self.from_number,
                to=self.to_number,
            )
            logger.info(f"✅ WhatsApp message sent! SID: {message.sid}, Status: {message.status}")
            return True

        except TwilioRestException as e:
            logger.error(f"❌ Twilio error: {e.code} - {e.msg}")
            if e.code == 21608:
                logger.error(
                    "💡 The recipient hasn't joined the WhatsApp sandbox. "
                    "Ask them to send 'join <keyword>' to your Twilio WhatsApp number."
                )
            elif e.code == 63032:
                logger.error(
                    "💡 WhatsApp sandbox session expired. "
                    "The recipient needs to re-join by sending 'join <keyword>'."
                )
            return False

        except Exception as e:
            logger.error(f"❌ Failed to send WhatsApp message: {e}")
            return False

    def send_alert(self, announcement: dict, summary: str = None) -> bool:
        """
        Send a formatted alert for an NSE announcement.

        Args:
            announcement: NSE announcement dict
            summary: Optional AI-generated summary

        Returns:
            True if sent successfully
        """
        symbol = announcement.get("symbol", "N/A")
        company = announcement.get("sm_name", announcement.get("companyName", symbol))
        subject = announcement.get("desc", announcement.get("subject", "No subject"))
        date = announcement.get("an_dt", announcement.get("date", "N/A"))
        category = announcement.get("attchmntText", announcement.get("category", ""))
        attachment = announcement.get("attchmntFile", announcement.get("attachment", ""))

        # Build the message
        lines = [
            "🔔 *NSE ALERT*",
            f"━━━━━━━━━━━━━━━━━━━━━",
            f"🏢 *{company}* ({symbol})",
            f"📅 {date}",
            f"",
            f"📋 *Subject:*",
            f"{subject}",
        ]

        if category:
            lines.append(f"\n📂 *Category:* {category}")

        if summary:
            lines.extend([
                f"",
                f"🤖 *AI Summary:*",
                f"{summary}",
            ])

        if attachment:
            # NSE attachment URLs
            if attachment.startswith("http"):
                pdf_url = attachment
            else:
                pdf_url = f"https://www.nseindia.com/corporate/{attachment}"
            lines.extend([
                f"",
                f"📎 *Document:*",
                f"{pdf_url}",
            ])

        lines.extend([
            f"",
            f"━━━━━━━━━━━━━━━━━━━━━",
            f"🔗 View on NSE: https://www.nseindia.com/companies-listing/corporate-filings-announcements",
        ])

        message = "\n".join(lines)
        return self.send_message(message)

    def send_startup_notification(self, watchlist: list) -> bool:
        """Send a notification when the agent starts monitoring."""
        symbols = ", ".join(watchlist)
        message = (
            "🚀 *NSE Alert Agent Started!*\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"Monitoring {len(watchlist)} companies:\n"
            f"📊 {symbols}\n\n"
            f"You'll receive alerts whenever new corporate filings are posted on NSE.\n"
            f"━━━━━━━━━━━━━━━━━━━━━"
        )
        return self.send_message(message)

    def send_error_notification(self, error_msg: str) -> bool:
        """Send error notification to admin."""
        message = (
            "⚠️ *NSE Alert Agent - Error*\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"{error_msg}\n"
            f"━━━━━━━━━━━━━━━━━━━━━"
        )
        return self.send_message(message)


# Quick test
if __name__ == "__main__":
    import os
    from dotenv import load_dotenv

    load_dotenv()
    logging.basicConfig(level=logging.DEBUG, format="%(asctime)s [%(levelname)s] %(message)s")

    sender = WhatsAppSender(
        account_sid=os.getenv("TWILIO_ACCOUNT_SID"),
        auth_token=os.getenv("TWILIO_AUTH_TOKEN"),
        from_number=os.getenv("TWILIO_WHATSAPP_FROM"),
        to_number=os.getenv("WHATSAPP_TO"),
    )

    sender.send_message("🧪 Test message from NSE Alert Agent!")
