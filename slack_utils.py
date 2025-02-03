import os
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
import logging

logger = logging.getLogger(__name__)

class SlackNotifier:
    def __init__(self):
        self.client = WebClient(token=os.getenv('SLACK_BOT_TOKEN'))
        self.default_channel = os.getenv('SLACK_CHANNEL_ID')

    def send_notification(self, message, channel=None, blocks=None):
        try:
            response = self.client.chat_postMessage(
                channel=channel or self.default_channel,
                text=message,
                blocks=blocks
            )
            return response
        except SlackApiError as e:
            logger.error(f"Error sending Slack notification: {e}")
            return None

    def send_scraper_error(self, pnr, airline, error_message, stage):
        blocks = [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": f"⚠️ {airline} Scraper Error"
                }
            },
            {
                "type": "section",
                "fields": [
                    {
                        "type": "mrkdwn",
                        "text": f"*PNR:*\n{pnr}"
                    },
                    {
                        "type": "mrkdwn",
                        "text": f"*Stage:*\n{stage}"
                    }
                ]
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Error:*\n```{error_message}```"
                }
            }
        ]
        return self.send_notification(f"Scraper Error - {airline} - PNR: {pnr}", blocks=blocks)

    def send_dom_change_alert(self, pnr, airline, changes):
        blocks = [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": f"🔄 {airline} DOM Changes Detected"
                }
            },
            {
                "type": "section",
                "fields": [
                    {
                        "type": "mrkdwn",
                        "text": f"*PNR:*\n{pnr}"
                    },
                    {
                        "type": "mrkdwn",
                        "text": f"*Changes Count:*\n{len(changes)}"
                    }
                ]
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "*First few changes:*\n```" + "\n".join(changes[:3]) + "```"
                }
            }
        ]
        return self.send_notification(f"DOM Changes - {airline} - PNR: {pnr}", blocks=blocks)
