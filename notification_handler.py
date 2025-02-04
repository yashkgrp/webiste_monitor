import logging
from email_utils import send_email, generate_status_email, generate_scraper_error_email, generate_dom_change_email, send_notification_email
from slack_utils import SlackNotifier
from datetime import datetime

logger = logging.getLogger(__name__)

class NotificationHandler:
    def __init__(self, db_ops):
        self.db_ops = db_ops
        self.slack = SlackNotifier()
        
    def _safe_send(self, notification_type, func, *args, **kwargs):
        """Safely execute notification sending functions"""
        try:
            return func(*args, **kwargs)
        except Exception as e:
            logger.error(f"Failed to send {notification_type} notification: {e}")
            return None

    def send_website_status_notification(self, url, status_type, error_message=None, 
                                      response_time=None, downtime_duration=None):
        """Send website status notifications to both email and Slack"""
        try:
            notification_emails = self.db_ops.get_notification_emails()
            timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

            if notification_emails:
                if status_type == 'down':
                    self._safe_send('email',
                        send_email,
                        subject=f"Website Down Alert - {url}",
                        body=generate_status_email(
                            url=url,
                            status="down",
                            error_message=error_message,
                            timestamp=timestamp
                        ),
                        to_email=notification_emails[0]
                    )
                else:  # recovery
                    self._safe_send('email',
                        send_email,
                        subject=f"Website Recovered - {url}",
                        body=generate_status_email(
                            url=url,
                            status="up",
                            downtime_duration=downtime_duration,
                            timestamp=timestamp
                        ),
                        to_email=notification_emails[0]
                    )

            # Send Slack notification
            if status_type == 'down':
                self._safe_send('slack',
                    self.slack.send_website_down_alert,
                    url=url,
                    error_message=error_message,
                    response_time=response_time
                )
            else:  # recovery
                self._safe_send('slack',
                    self.slack.send_website_recovery_alert,
                    url=url,
                    downtime_duration=downtime_duration,
                    response_time=response_time
                )

        except Exception as e:
            logger.error(f"Error in send_website_status_notification: {e}")

    def send_scraper_notification(self, error, data, stage, airline="Star Air"):
        """Send scraper notifications to both email and Slack"""
        try:
            print("notification email being sent")
            notification_emails = self.db_ops.get_notification_emails()
            print(str(notification_emails))
            timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            error_msg = str(error)
            print("yash")

            if notification_emails:
                print("yash2")
                self._safe_send('email',
                    send_notification_email,
                    subject=f"{airline} Scraper Error - {stage}",
                    html_content=generate_scraper_error_email(
                        pnr=data.get('Ticket/PNR', 'N/A'),
                        gstin=data.get('Traveller Name', 'N/A'),
                        error_message=error_msg,
                        timestamp=timestamp,
                        stage=stage
                    ),
                    notification_emails=notification_emails
                )

            # self._safe_send('slack',
            #     self.slack.send_scraper_error,
            #     pnr=data.get('Ticket/PNR', 'N/A'),
            #     airline=airline,
            #     error_message=error_msg,
            #     stage=stage
            # )

        except Exception as e:
            print(f"Error in send_scraper_notification: {e}")
            logger.error(f"Error in send_scraper_notification: {e}")

    def send_dom_change_notification(self, changes, gstin, pnr, airline="Star Air"):
        """Send DOM change notifications to both email and Slack"""
        try:
            if not changes:
                return

            notification_emails = self.db_ops.get_notification_emails()
            timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

            if notification_emails:
                self._safe_send('email',
                    send_notification_email,
                    subject=f"DOM Changes Detected - PNR: {pnr}",
                    html_content=generate_dom_change_email(
                        pnr=pnr,
                        gstin=gstin,
                        changes=changes,
                        timestamp=timestamp
                    ),
                    notification_emails=notification_emails
                )

            self._safe_send('slack',
                self.slack.send_dom_change_alert,
                pnr=pnr,
                airline=airline,
                changes=changes
            )

        except Exception as e:
            logger.error(f"Error in send_dom_change_notification: {e}")
