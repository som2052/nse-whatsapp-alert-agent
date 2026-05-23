"""
Announcement Summarizer
========================
Summarizes NSE corporate announcements into investor-friendly WhatsApp messages.
Supports both AI-powered (Anthropic Claude) and rule-based summarization.
"""

import logging
import re
from typing import Optional

logger = logging.getLogger(__name__)


class AnnouncementSummarizer:
    """
    Generates concise summaries of NSE corporate announcements.

    Two modes:
    1. AI Mode (requires Anthropic API key) - Uses Claude for intelligent summaries
    2. Rule-based Mode (fallback) - Extracts key info using patterns
    """

    # Announcement categories and their investor significance
    CATEGORY_SIGNIFICANCE = {
        "Board Meeting": "🔴 HIGH",
        "Financial Results": "🔴 HIGH",
        "Dividend": "🔴 HIGH",
        "Bonus": "🔴 HIGH",
        "Stock Split": "🔴 HIGH",
        "Buyback": "🔴 HIGH",
        "Merger": "🔴 HIGH",
        "Acquisition": "🔴 HIGH",
        "Rights Issue": "🟡 MEDIUM",
        "AGM/EGM": "🟡 MEDIUM",
        "Change in Directors": "🟡 MEDIUM",
        "Credit Rating": "🟡 MEDIUM",
        "Related Party": "🟡 MEDIUM",
        "Insider Trading": "🟡 MEDIUM",
        "General": "🟢 LOW",
        "Compliance": "🟢 LOW",
        "Others": "🟢 LOW",
    }

    def __init__(self, anthropic_api_key: Optional[str] = None):
        """
        Initialize summarizer.

        Args:
            anthropic_api_key: Optional Anthropic API key for AI summarization
        """
        self.ai_enabled = False
        self.client = None

        if anthropic_api_key:
            try:
                import anthropic
                self.client = anthropic.Anthropic(api_key=anthropic_api_key)
                self.ai_enabled = True
                logger.info("🤖 AI summarization enabled (Anthropic Claude)")
            except ImportError:
                logger.warning("⚠️ anthropic package not installed. Using rule-based summarization.")
            except Exception as e:
                logger.warning(f"⚠️ Failed to initialize Anthropic client: {e}. Using rule-based mode.")
        else:
            logger.info("📝 Using rule-based summarization (no Anthropic API key)")

    def summarize(self, announcement: dict) -> str:
        """
        Generate a summary for an announcement.

        Args:
            announcement: NSE announcement dict

        Returns:
            Summary string
        """
        if self.ai_enabled:
            return self._ai_summarize(announcement)
        return self._rule_based_summarize(announcement)

    def _ai_summarize(self, announcement: dict) -> str:
        """Use Claude to generate an investor-focused summary."""
        subject = announcement.get("desc", announcement.get("subject", ""))
        symbol = announcement.get("symbol", "")
        company = announcement.get("sm_name", announcement.get("companyName", symbol))
        category = announcement.get("attchmntText", announcement.get("category", ""))

        prompt = f"""You are an Indian stock market analyst. Summarize this NSE corporate announcement for an SME investor in 2-3 crisp sentences. Focus on: what happened, investor impact, and any action needed.

Company: {company} ({symbol})
Category: {category}
Subject: {subject}

Rules:
- Be concise (max 150 words)
- Highlight financial impact if any
- Use plain language, no jargon
- If it's a board meeting notice, mention what's likely to be discussed
- If it's financial results, highlight key numbers if mentioned
- Add significance: HIGH/MEDIUM/LOW for an SME investor"""

        try:
            message = self.client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=300,
                messages=[{"role": "user", "content": prompt}],
            )
            summary = message.content[0].text.strip()
            logger.debug(f"🤖 AI summary generated for {symbol}: {summary[:100]}...")
            return summary

        except Exception as e:
            logger.warning(f"⚠️ AI summarization failed: {e}. Falling back to rule-based.")
            return self._rule_based_summarize(announcement)

    def _rule_based_summarize(self, announcement: dict) -> str:
        """Generate a structured summary using pattern matching."""
        subject = announcement.get("desc", announcement.get("subject", ""))
        category = announcement.get("attchmntText", announcement.get("category", "General"))

        # Determine significance
        significance = "🟢 LOW"
        for cat_key, sig in self.CATEGORY_SIGNIFICANCE.items():
            if cat_key.lower() in subject.lower() or cat_key.lower() in category.lower():
                significance = sig
                break

        # Extract key patterns
        summary_parts = []

        # Financial results
        if any(kw in subject.lower() for kw in ["financial result", "quarterly result", "annual result"]):
            significance = "🔴 HIGH"
            summary_parts.append("📊 Financial results announced")
            if "quarter" in subject.lower():
                q_match = re.search(r'(Q[1-4]|first|second|third|fourth)\s*(quarter)?', subject, re.IGNORECASE)
                if q_match:
                    summary_parts.append(f"Period: {q_match.group(0).strip()}")

        # Board meeting
        elif "board meeting" in subject.lower():
            significance = "🔴 HIGH"
            summary_parts.append("🏛️ Board meeting scheduled")
            if "dividend" in subject.lower():
                summary_parts.append("Agenda may include dividend declaration")
            if "result" in subject.lower():
                summary_parts.append("Financial results to be considered")

        # Dividend
        elif "dividend" in subject.lower():
            significance = "🔴 HIGH"
            summary_parts.append("💰 Dividend announcement")
            amount_match = re.search(r'(?:Rs\.?|₹)\s*(\d+\.?\d*)', subject)
            if amount_match:
                summary_parts.append(f"Amount: ₹{amount_match.group(1)} per share")

        # Bonus/Split
        elif "bonus" in subject.lower():
            significance = "🔴 HIGH"
            ratio_match = re.search(r'(\d+)\s*:\s*(\d+)', subject)
            if ratio_match:
                summary_parts.append(f"🎁 Bonus issue: {ratio_match.group(0)}")
            else:
                summary_parts.append("🎁 Bonus issue announced")

        elif "split" in subject.lower():
            significance = "🔴 HIGH"
            summary_parts.append("✂️ Stock split announced")

        # AGM/EGM
        elif any(kw in subject.lower() for kw in ["agm", "egm", "annual general", "extraordinary general"]):
            significance = "🟡 MEDIUM"
            summary_parts.append("📋 General meeting notice")

        # Credit Rating
        elif "rating" in subject.lower() or "credit" in subject.lower():
            significance = "🟡 MEDIUM"
            summary_parts.append("📊 Credit rating update")

        # Insider trading / SAST
        elif any(kw in subject.lower() for kw in ["insider", "sast", "acquisition of shares"]):
            significance = "🟡 MEDIUM"
            summary_parts.append("👤 Insider trading / shareholding disclosure")

        # Default
        else:
            # Clean up and shorten the subject
            clean_subject = subject[:200] if len(subject) > 200 else subject
            summary_parts.append(f"📌 {clean_subject}")

        # Add significance
        summary_parts.insert(0, f"Significance: {significance}")

        return "\n".join(summary_parts)

    def get_priority(self, announcement: dict) -> int:
        """
        Get priority level for an announcement (1=highest, 3=lowest).
        Useful for filtering or ordering alerts.
        """
        subject = announcement.get("desc", announcement.get("subject", "")).lower()
        category = announcement.get("attchmntText", announcement.get("category", "")).lower()

        high_keywords = ["financial result", "board meeting", "dividend", "bonus", "split", "buyback", "merger", "acquisition"]
        medium_keywords = ["agm", "egm", "credit rating", "director", "insider", "rights issue"]

        combined = subject + " " + category
        if any(kw in combined for kw in high_keywords):
            return 1
        if any(kw in combined for kw in medium_keywords):
            return 2
        return 3


# Quick test
if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)

    summarizer = AnnouncementSummarizer()

    test_announcement = {
        "symbol": "RELIANCE",
        "sm_name": "Reliance Industries Ltd",
        "desc": "Board Meeting Intimation for Consideration of Financial Results for the quarter ended March 2025 and Dividend",
        "attchmntText": "Board Meeting",
        "an_dt": "23-May-2026",
    }

    summary = summarizer.summarize(test_announcement)
    print(f"\nSummary:\n{summary}")
    print(f"\nPriority: {summarizer.get_priority(test_announcement)}")
