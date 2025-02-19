import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email_logger import email_logger
from smtp_logger import smtp_logger

# ...existing code...

def generate_status_email(url, status, timestamp, error_message=None, downtime_duration=None):
    """Generate email body for website status changes"""
    logo_url = "https://i.postimg.cc/0NNr0tmK/Frame-2.png"
    
    if status == "down":
        color = "#dc3545"  # red
        status_message = f"Website is DOWN: {error_message}"
    else:
        color = "#28a745"  # green
        status_message = f"Website is back UP (Was down for {downtime_duration})"

    return f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Website Status Alert</title>
        <style>
            body {{
                font-family: Arial, sans-serif;
                background-color: #f4f4f4;
                margin: 0;
                padding: 0;
            }}
            .container {{
                max-width: 600px;
                margin: 50px auto;
                background-color: #ffffff;
                padding: 20px;
                border-radius: 8px;
                box-shadow: 0 0 10px rgba(0, 0, 0, 0.1);
            }}
            .header {{
                text-align: center;
                padding: 10px 0;
                border-bottom: 1px solid #dddddd;
            }}
            .status {{
                color: {color};
                font-weight: bold;
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="logo">
                <img src="{logo_url}" alt="Logo" style="max-width: 150px;">
            </div>
            <div class="header">
                <h2>Website Status Alert</h2>
            </div>
            <div class="content">
                <p><strong>URL:</strong> <a href="{url}">{url}</a></p>
                <p class="status">{status_message}</p>
                <p><strong>Time:</strong> {timestamp}</p>
            </div>
        </div>
    </body>
    </html>
    """

def generate_scraper_error_email(pnr, gstin, error_message, timestamp, stage=None, scraper_name=None):
    """Generate email body for scraper errors"""
    logo_url = "https://i.postimg.cc/0NNr0tmK/Frame-2.png"
    
    return f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <title>Scraper Error Alert</title>
        <style>
            body {{ font-family: Arial, sans-serif; }}
            .error-box {{ 
                background-color: #ffebee; 
                border: 1px solid #dc3545;
                padding: 15px;
                border-radius: 4px;
                margin: 10px 0;
            }}
            .stage {{ color: #856404; }}
            .scraper-name {{ 
                color: #0d6efd;
                font-weight: bold;
            }}
        </style>
    </head>
    <body>
        <div>
            <img src="{logo_url}" alt="Logo" style="max-width: 150px;">
            <h2>Scraper Error Alert</h2>
            {f'<p><strong>Scraper:</strong> <span class="scraper-name">{scraper_name}</span></p>' if scraper_name else ''}
            <p><strong>PNR:</strong> {pnr}</p>
            <p><strong>GSTIN:</strong> {gstin}</p>
            {f'<p><strong>Stage:</strong> <span class="stage">{stage}</span></p>' if stage else ''}
            <p><strong>Time:</strong> {timestamp}</p>
            <div class="error-box">
                <strong>Error:</strong><br>
                {error_message}
            </div>
        </div>
    </body>
    </html>
    """

def generate_dom_change_email(pnr, gstin, changes, timestamp):
    """Generate email body for DOM changes with formatted changes"""
    logo_url = "https://i.postimg.cc/0NNr0tmK/Frame-2.png"
    
    def escape_html(text):
        """Escape HTML content properly"""
        return (text.replace('&', '&amp;')
                   .replace('<', '&lt;')
                   .replace('>', '&gt;')
                   .replace('"', '&quot;')
                   .replace("'", '&#39;'))
    
    changes_html = ""
    for change in changes:
        type_color = {
            'added': '#28a745',
            'removed': '#dc3545',
            'modified': '#0d6efd'
        }.get(change.get('type', 'modified'), '#6c757d')
        
        changes_html += f"""
            <div style="margin: 10px 0; padding: 10px; border-left: 4px solid {type_color}; background-color: #f8f9fa;">
                <div style="color: #666; font-size: 0.9em;">
                    <strong>Path:</strong> {escape_html(str(change.get('path', 'N/A')))}
                </div>
                <div style="font-family: monospace; margin: 8px 0; padding: 8px; background: #fff; border-radius: 4px;">
                    <strong>Element:</strong><br>
                    <pre style="white-space: pre-wrap; word-wrap: break-word; margin: 0;">{escape_html(str(change.get('element', 'N/A')))}</pre>
                </div>
                <div style="font-style: italic; color: {type_color};">
                    {escape_html(str(change.get('description', 'No description available')))}
                </div>
            </div>
        """

    return f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <title>DOM Changes Detected</title>
    </head>
    <body style="font-family: Arial, sans-serif;">
        <div>
            <img src="{logo_url}" alt="Logo" style="max-width: 150px;">
            <h2>DOM Changes Detected</h2>
            <p><strong>PNR:</strong> {pnr}</p>
            <p><strong>GSTIN:</strong> {gstin}</p>
            <p><strong>Time:</strong> {timestamp}</p>
            <h3>Changes Detected:</h3>
            <div style="margin-top: 20px;">
                {changes_html}
            </div>
        </div>
    </body>
    </html>
    """

def send_notification_email(subject, html_content, notification_emails=None):
    """Send email to all notification emails"""
    if notification_emails is None:
        notification_emails = os.getenv('SMTP_NOTIFICATIONEMAIL', '').split(',')
    
    for email in notification_emails:
        try:
            print("yash3")
            send_email(subject=subject, body=html_content, to_email=email.strip())
        except Exception as e:
            logger.error(f"Failed to send notification email to {email}: {e}")

def send_email(subject='', body='', to_email=os.getenv('SMTP_NOTIFICATIONEMAIL')):
    try:
        smtp_server = os.getenv('SMTP_SERVER', 'smtp.gmail.com')
        smtp_port = int(os.getenv('SMTP_PORT', 587))
        smtp_user = os.getenv('SMTP_USER')
        
        smtp_password = os.getenv('SMTP_PASSWORD')

        msg = MIMEMultipart()
        msg['From'] = smtp_user
        msg['To'] = to_email
        msg['Subject'] = subject
        msg.attach(MIMEText(body, 'html'))

        # Log SMTP connection attempt
        smtp_logger.log_connection(smtp_server, smtp_port)
        
        server = smtplib.SMTP(smtp_server, smtp_port)
        
        # Log TLS start
        smtp_logger.log_tls()
        server.starttls()
        
        # Log login attempt
        smtp_logger.log_login(smtp_user)
        server.login(smtp_user, smtp_password)
        
        server.send_message(msg)
        server.quit()
        print("yash4")
        
        # Log successful email send
        status_type = 'DOWN' if 'Down Alert' in subject else 'UP' if 'Recovered' in subject else 'OTHER'
        email_logger.log_email_sent(to_email, subject, status_type)
        
    except smtplib.SMTPAuthenticationError as e:
        smtp_logger.log_error('authentication', str(e))
        email_logger.log_email_error(to_email, subject, f"Authentication failed: {str(e)}")
    except smtplib.SMTPException as e:
        smtp_logger.log_error('operation', str(e))
        email_logger.log_email_error(to_email, subject, str(e))
    except Exception as e:
        smtp_logger.log_error('unknown', str(e))
        email_logger.log_email_error(to_email, subject, str(e))

# ...rest of existing code...
