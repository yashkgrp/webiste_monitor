import logging
import time
import requests
import pdfkit
import re
import os
import difflib
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from datetime import datetime
from socket_logger import SocketLogger
import sys

# Add wkhtmltopdf configuration

# Update this path to the correct location of wkhtmltopdf executable
WKHTMLTOPDF_PATH = r'C:\Program Files\wkhtmltopdf\bin\wkhtmltopdf.exe'  # Windows example
# WKHTMLTOPDF_PATH = '/usr/local/bin/wkhtmltopdf'  # macOS/Linux example

# Configure pdfkit with path
PDF_CONFIG = pdfkit.configuration(wkhtmltopdf=WKHTMLTOPDF_PATH)

# Update the PDF configuration with more options


logger = logging.getLogger(__name__)
socket_logger = SocketLogger()

class StarAirScraper:
    def __init__(self, db_ops, socketio=None):
        self.db_ops = db_ops
        self.socketio = socketio
        self.session = requests.Session()
        self.base_url = 'https://starair.in/customer'
        self.timing_data = {}
        self.dom_changes = []
        self.current_stage = 'initialization'

        # Create temp directory if it doesn't exist
        if not os.path.exists('temp'):
            os.makedirs('temp')

    def emit_status(self, stage, status, message, timing=None, error=None):
        """Emit status updates to socket and logs"""
        if self.socketio:
            try:
                data = {
                    'stage': stage,
                    'status': status,
                    'message': message,
                    'timing': timing,
                    'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                }
                if error:
                    data['error'] = str(error)
                
                # Emit multiple event types for better UI updates
                self.socketio.emit('scraper_status', data)
                self.socketio.emit('scraper_event', {
                    'type': 'status' if status != 'error' else 'error',
                    'message': f"{stage.title()}: {message}"
                })
                self.socketio.emit('scraper_stage', data)
                
                # Add a general status update
                self.socketio.emit('scraper_general_status', {
                    'status': status,
                    'message': f"{stage.title()}: {message}",
                    'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                })
            except Exception as e:
                socket_logger.log_error(stage, f"Failed to emit status: {str(e)}")
                logger.error(f"Socket emission error: {e}")

    def login(self, book_code, gstin):
        """Handle login stage"""
        self.current_stage = 'login'
        self.emit_status(self.current_stage, 'starting', 'Preparing login request')
        
        login_start = time.time()
        try:
            # Get login page
            login_url = f'{self.base_url}/gstinvoice'
            response = self.session.get(login_url)
            response.raise_for_status()

            # Check for DOM changes
            has_changes, changes = self.db_ops.store_dom_snapshot('login_page', response.text)
            if has_changes:
                self.dom_changes = changes
                self.emit_status(self.current_stage, 'warning', 'Page structure changed', error="DOM changes detected")

            # Extract form token
            soup = BeautifulSoup(response.content, 'html.parser')
            token = soup.find('input', {'name': '__RequestVerificationToken'})
            if not token:
                raise ValueError("Security token not found")

            # Submit login
            payload = {
                'Book_code': book_code,
                'CustGSTIN': gstin,
                '__RequestVerificationToken': token['value'],
                'action': 'Search'
            }
            response = self.session.post(login_url, data=payload)
            response.raise_for_status()

            if response.url != login_url:
                raise ValueError("Login failed - invalid credentials")

            login_end = time.time()
            self.timing_data['login_time'] = round(login_end - login_start, 3)
            self.emit_status(self.current_stage, 'success', 'Login successful', self.timing_data['login_time'])
            return response

        except Exception as e:
            self.emit_status(self.current_stage, 'error', str(e), error=e)
            raise

    def find_invoice_links(self, response):
        """Handle navigation stage"""
        self.current_stage = 'navigation'
        self.emit_status(self.current_stage, 'starting', 'Searching for invoice links')

        nav_start = time.time()
        try:
            soup = BeautifulSoup(response.content, 'html.parser')
            links = soup.find_all('a', href=True, string='Print')
            
            if not links:
                raise ValueError("No invoice links found")

            nav_end = time.time()
            self.timing_data['navigation_time'] = round(nav_end - nav_start, 3)
            self.emit_status(self.current_stage, 'success', f'Found {len(links)} invoices', self.timing_data['navigation_time'])
            return links

        except Exception as e:
            self.emit_status(self.current_stage, 'error', str(e), error=e)
            raise

    def download_invoices(self, links, gstin, book_code):
        """Handle download stage"""
        self.current_stage = 'download'
        self.emit_status(self.current_stage, 'starting', f'Processing {len(links)} invoices')

        download_start = time.time()
        pdf_s3links = []

        try:
            for i, link in enumerate(links, 1):
                self.process_single_invoice(link, i, len(links), gstin, book_code)

            download_end = time.time()
            self.timing_data['download_time'] = round(download_end - download_start, 3)
            self.emit_status(self.current_stage, 'success', 'All invoices processed', self.timing_data['download_time'])
            return pdf_s3links

        except Exception as e:
            self.emit_status(self.current_stage, 'error', str(e), error=e)
            raise

    def process_single_invoice(self, link, index, total, gstin, book_code):
        """Process a single invoice"""
        self.emit_status(self.current_stage, 'progress', f'Processing invoice {index}/{total}')

        try:
            # Extract and validate link
            html = str(link)
            pattern = r'href="([^"]*)"'
            match = re.search(pattern, html)
            if match:
                href_value = match.group(1)  # Get the URL from the href attribute
                base_url = 'https://starair.in/customer'
                invoice_url = urljoin(base_url, href_value)
                invoice_response = self.session.get(invoice_url)
                invoice_response.raise_for_status()

                # Convert to PDF with enhanced error handling
                pdf_filename = f"{gstin}_{book_code}_invoice_{index}.pdf"
                pdf_path = os.path.join('temp', pdf_filename)

                try:
                    # Pre-process HTML content
                    html_content = invoice_response.content.decode('utf-8')
                    
                    # Convert HTML string to PDF
                    pdfkit.from_string(
                        html_content,
                        pdf_path,
                        options={"enable-local-file-access": ""},
                        configuration=PDF_CONFIG,
                        verbose=True
                    )
                    logging.info(f"Invoice {index}: PDF saved successfully at {pdf_filename}")

                    # Verify PDF was created successfully
                    if not os.path.exists(pdf_path) or os.path.getsize(pdf_path) == 0:
                        raise Exception("PDF file was not created successfully")

                    self.emit_status(self.current_stage, 'progress', f'Successfully converted invoice {index}')

                except Exception as e:
                    logging.error(f"Error converting Invoice {index} to PDF: {str(e)}")
                    self.emit_status(self.current_stage, 'error', f"Failed to convert invoice {index} to PDF", error=e)
                    raise

                # Verify PDF file creation
                if os.path.exists(pdf_path) and os.path.getsize(pdf_path) > 0:
                    logging.info(f"Invoice {index}: PDF file verified successfully at {pdf_path}")
                    self.emit_status(self.current_stage, 'progress', f'PDF file verified successfully for invoice {index}')
                else:
                    logging.error(f"Invoice {index}: PDF file verification failed at {pdf_path}")
                    self.emit_status(self.current_stage, 'error', f'PDF file verification failed for invoice {index}')
                    raise Exception("PDF file verification failed")

                # Clean up PDF file
                if os.path.exists(pdf_path):
                    os.remove(pdf_path)
                    logging.info(f"{pdf_path} has been deleted.")
                    self.emit_status(self.current_stage, 'progress', f'{pdf_path} has been deleted.')
                else:
                    logging.info(f"{pdf_path} does not exist.")
                    self.emit_status(self.current_stage, 'error', f'{pdf_path} does not exist.')

            else:
                raise ValueError(f"Invalid link format for invoice {index}")

        except Exception as e:
            self.emit_status(self.current_stage, 'error', f"Failed to process invoice {index}: {str(e)}", error=e)
            raise

def run_scraper(data, db_ops, socketio=None):
    """Main scraper entry point"""
    scraper = StarAirScraper(db_ops, socketio)
    
    try:
        # Initialize with explicit status
        start_time = time.time()
        scraper.emit_status('initialization', 'starting', 'Initializing scraper components')
        
        # Add delay for UI update
        time.sleep(1)
        
        # Login with progress status
        scraper.emit_status('login', 'progress', 'Preparing login request')
        response = scraper.login(data['Ticket/PNR'], data['Customer_GSTIN'])
        
        # Add delay for UI update
        time.sleep(1)
        
        # Find invoice links with status
        scraper.emit_status('navigation', 'progress', 'Searching for invoice documents')
        links = scraper.find_invoice_links(response)
        
        # Download and process with status updates
        scraper.emit_status('download', 'progress', f'Found {len(links)} invoices to process')
        pdf_s3links = scraper.download_invoices(links, data['Customer_GSTIN'], data['Ticket/PNR'])

        # Calculate total time and complete
        end_time = time.time()
        scraper.timing_data['total_run'] = round(end_time - start_time, 3)
        scraper.emit_status('completion', 'success', 'Scraping completed successfully')

        return {
            "success": True,
            "message": "FILE_PUSHED_TO_S3",
            "data": {
                "s3_link": pdf_s3links,
                "airline": 'starair',
                "timing": scraper.timing_data,
                "dom_changes": scraper.dom_changes
            }
        }

    except Exception as e:
        logger.error(f"Scraper failed: {str(e)}")
        return {
            "success": False,
            "message": str(e),
            "data": {}
        }
