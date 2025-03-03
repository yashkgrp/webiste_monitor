import requests
from requests import JSONDecodeError
import json
import os
import time
import string
import random
import base64
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
import logging
from logging.handlers import TimedRotatingFileHandler
import chromedriver_autoinstaller
import pytz

# Configure the logging
ist = pytz.timezone('Asia/Kolkata')
folder_path = "log/"
if not os.path.exists(folder_path):
    os.makedirs(folder_path)

log_handler = TimedRotatingFileHandler(
    folder_path + 'indigo_scraper.log',  # Base file name
    when='D',  # Rotate by day
    interval=1,  # Rotate every 1 day
    backupCount=7,  # Keep only the last 7 log files
    encoding='utf-8',
    delay=False
)

formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(lineno)d - %(message)s')
log_handler.setFormatter(formatter)
logging.basicConfig(
    level=logging.INFO,
    handlers=[log_handler, logging.StreamHandler()]  # Add StreamHandler for console output
)


HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:109.0) Gecko/20100101 Firefox/112.0",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Accept-Encoding": "gzip, deflate, br",
    "Referer": "https://www.goindigo.in/",
    "Upgrade-Insecure-Requests": "1",
    "Connection": "keep-alive",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "TE": "trailers"
}

COOLDOWN_SECS = 10

def format_html(session, html):
    soup = BeautifulSoup(html, "html.parser")
    for x in soup.find_all("div", {"role": "dialog"}):
        x.decompose()
    for x in soup.find_all("noscript"):
        x.decompose()
    for x in soup.find_all("script"):
        x.decompose()
    soup.find("div", {"class": "imgloaderGif"}).decompose()
    imgs = soup.find_all("img")
    resource_url = "https://book.goindigo.in/"
    for x in imgs:
        try:
            b64_img = base64.b64encode(
                session.get(
                    resource_url + x.attrs["src"],
                    headers=HEADERS
                ).content
            )
            x.attrs["src"] = "data:image/png;base64," + b64_img.decode()
        except TimeoutError as e:
            return None, f'FAILED_TO_LOAD_IMAGES_INVOICE - {e}'

    return str(soup), 'ok'


def get_pdf_from_html(driver, invoiceID, html):
    try:
        file_path = os.path.join('pdf_folder/', invoiceID+'.html')
        with open(file_path, "w+") as f:
            f.write(html)

        driver.get(f'file://{os.path.join(os.getcwd(), file_path)}')
        pdf_data = driver.execute_cdp_cmd(
            "Page.printToPDF", {"path": "html-page.pdf", "format": "A4"}
        )
        b64 = pdf_data["data"]
        # os.remove(file_path)
        return b64, 'ok'
    except Exception as e:
        return None, f'FAILED_TO_PARSE_PDF - {e}'


def initiate_webdriver(download_dir=None, retry = 0):
    try:
        if not download_dir:
            download_dir = os.getcwd()
        options = webdriver.ChromeOptions()
        prefs = {
            "credentials_enable_service": False,
            "profile.password_manager_enabled": False,
            "directory_upgrade": True
        }
        options.add_experimental_option("prefs", prefs)
        options.add_experimental_option("excludeSwitches", ['enable-automation'])
        options.add_argument("--disable-popup-blocking")
        options.add_argument("--window-size=1920,1400")
        options.add_argument('--disable-gpu')
        options.add_argument('--headless')
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-dev-shm-usage')
        driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
        driver.implicitly_wait(1)
        return driver
    except:
        if retry < 5:
            return initiate_webdriver(download_dir, retry+1)
        raise Exception("Webdriver failed")

def init_session(PORT):
    PROXY_URL = f'https://user-finkraftscraper-sessionduration-1:7o_ycvJzWs3s8f6RmR@gate.smartproxy.com:{PORT}'
    proxies = {
        'http': PROXY_URL,
        'https': PROXY_URL
    }
    """
    :return: returns a requests session
    """
    current_session = requests.currentSession = requests.Session()
    current_session.proxies.update(proxies)
    url = 'https://www.goindigo.in/view-gst-invoice.html'
    try:
        _ = current_session.get(url, headers=HEADERS)
    except Exception as e:
        current_session = None
        current_session_mssg = f'FAILED_TO_INIT_WEBSESSION - {e}'
        return current_session,current_session_mssg
    current_session_mssg = 'ok'
    return current_session,current_session_mssg


def get_invoiceids_for_pnr(session, pnr, ssr_email):
    """
    :param session: requests session
    :param pnr: 6 alphanum PNR
    :return: email address and list of invoice IDs set(string)
    """

    url = 'https://book.goindigo.in/booking/ValidateGSTInvoiceDetails'

    params = {
        'indigoGSTDetails.PNR': pnr,
        'indigoGSTDetails.email': ssr_email
    }

    try:
        r = session.get(url, params=params, headers=HEADERS)
    except ConnectionError as e:
        return None, f'FAILED_TO_GET_INVOICEID - {e}'

    if r.status_code != 200:
        if r.status_code ==403:
            return None, f'403'
        else:
            return None, f'FAILED_TO_GET_INVOICEID - HTTP_STATUS:{r.status_code} - TEXT:{r.text}'

    invoice_numbers = set()
    try:
        r_obj = r.json()
        if gst_details := r_obj.get("indigoGSTDetails"):
            if msg := gst_details.get('errorMessage'):
                return None, f'FAILED_TO_GET_INVOICEID - {msg}'
            for x in gst_details["invoiceDetails"]["objInvoiceDetails"]:
                invoice_numbers.add(x["invoiceNumber"])
            return list(invoice_numbers), 'ok'
        else:
            return  None, r_obj
    except JSONDecodeError as e:
        return None, f'FAILED_TO_GET_INVOICEID - HTTP_STATUS:{r.status_code} - TEXT: {r.text}'


def get_auth_token_session(session, email=None, pnr=None, invoice_id=None):
    """
    :param session: requests session
    :param email: email id used to Get invoice IDS
    :param pnr: 6 alphanum PNR
    :param invoice_id: Invoice ID for the invoice
    :returns auth token
    """

    url = 'https://book.goindigo.in/Booking/GSTInvoiceDetails'
    data = None
    if pnr:
        data = {
            'indigoGSTDetails.PNR': pnr,
            'indigoGSTDetails.CustEmail': email,
            'indigoGSTDetails.InvoiceNumber': '',
            'indigoGSTDetails.InvoiceEmail': ''
        }
    elif invoice_id:
        data = {
            'indigoGSTDetails.IsIndigoSkin': 'true',
            'indigoGSTDetails.PNR': '',
            'indigoGSTDetails.InvoiceNumber': invoice_id,
            'GstRetrieve': 'Retrieve'
        }
    try:
        r = session.post(url, data=data, headers=HEADERS)
    except ConnectionError as e:
        return None, f'FAILED_TO_CONNECT_TO_AUTH - {e}'

    if r.status_code != 200:
        return None, f'FAILED_AUTH_TOKEN_REQUEST - HTTP_STATUS:{r.status_code} - TEXT:{r.text}'

    soup = BeautifulSoup(r.content, "html.parser")
    try:
        request_verification_token = soup.find(
            "input", attrs={"name": "__RequestVerificationToken"})['value']
    except AttributeError as e:
        return None, 'FAILED_SEARCH_AUTH_TOKEN_IN_FORM'
    return request_verification_token, 'ok'


import time
import requests
from requests.exceptions import SSLError

def get_invoice_for_invoiceid(session, auth_token, invoice_id):
    """
    :param session: requests session
    :param auth_token:
    :param invoice_id:
    :return: html invoice
    """
    url = 'https://book.goindigo.in/Booking/GSTInvoice'
    data = {
        '__RequestVerificationToken': auth_token,
        'IndigoGSTInvoice.InvoiceNumber': invoice_id,
        'IndigoGSTInvoice.IsPrint': 'false',
        'IndigoGSTInvoice.isExempted': '',
        'IndigoGSTInvoice.ExemptedMsg': ''
    }

    retry_attempts = 3  # Number of retries
    for attempt in range(1, retry_attempts + 1):
        try:
            r = session.post(url, data=data, headers=HEADERS)
            if r.status_code != 200:
                return None, f'FAILED_INVOICE_FETCH_REQUEST - HTTP_STATUS:{r.status_code} - TEXT:{r.text}'
            else:
                return r.content, 'ok'

        except SSLError as ssl_error:
            if attempt < retry_attempts:
                logging.info(f"Retrying API for the {attempt+1} time due to SSL error: {str(ssl_error)}")
                time.sleep(3)  # Sleep before retrying
            else:
                return None, f"SSL Error after {retry_attempts} retries: {str(ssl_error)}"


def save_file(byte_content, object_name):
    file_path = 'pdf_folder/'
    os.makedirs(file_path, exist_ok=True)

    with open(os.path.join(file_path, object_name), 'wb') as f:
        f.write(byte_content)

    # Print the file path to ensure the file is being saved correctly
    logging.info(f"Saving file to: {os.path.join(file_path, object_name)}")

    status, s3link = upload.upload_file(os.path.join(file_path, object_name), object_name, 'indigo')

    # Check the return values from upload_file function
    logging.info(f"Upload result - Status: {status}, S3 Link: {s3link}")

    return status, s3link


def indigo_scraper(ticket_pnr, ssr_email_list, count, PORT):
    try:
        logging.info(f"PNR: ", ticket_pnr)
        logging.info(f"SSR_EMAIL_LIST: ", ssr_email_list)
        
        for ssr_email in ssr_email_list:  # Loop through the list of SSR emails
            logging.info(f"Trying with SSR Email: {ssr_email}")
            
            # Call the indigo_scraper_pnr function for each email
            response = indigo_scraper_pnr(ticket_pnr, ssr_email, count, PORT)
            
            if response['success']:  # If scraping is successful
                return response  # Return the response immediately if successful
            
            else:  # If scraping fails for the current SSR email
                logging.info(f"Failed for SSR Email: {ssr_email}. Error: {response['message']}")
        
        # If all emails fail, return the last failure message from indigo_scraper_pnr
        return {
            "success": False,
            "message": response['message'],  # Return the last error message
            "data": {}
        }
    
    except Exception as e:
        return {
            "success": False,
            "message": e.args[0],
            "data": {}
        }


def indigo_scraper_pnr(pnr, ssr_email, count, PORT):
    try:
        inv_status = []
        if count == 0:
            current_session,current_session_mssg=init_session(PORT)
        curr_sess = current_session
        msg = current_session_mssg
        logging.info(f"curr_sess", curr_sess)
        logging.info(f"msg", msg)
        if msg != 'ok':
            return {
                "success": False,
                "message": "ERROR INIT PORTAL ISSUE",
                "data": {}
            }

        invoice_ids, msg = get_invoiceids_for_pnr(curr_sess, pnr, ssr_email)
        logging.info(f"invoice_ids", invoice_ids)    
        if msg != 'ok':
            if msg == '403':
                return {
                    "success": False,
                    "message": "IP BLOCKED PORTAL ISSUE",
                    "data": {}
                }
            else:  
                return {
                    "success": False,
                    "message": "ERROR INVOICE ID PORTAL ISSUE",
                    "data": {}
                }

        auth_token, msg = get_auth_token_session(curr_sess, ssr_email, pnr)
        logging.info(f"auth_token", auth_token)   
        if msg != 'ok':
            return {
                "success": False,
                "message": "ERROR AUTH TOKEN PORTAL ISSUE",
                "data": {}
            }
        
        html_links = []
        for invoiceID in invoice_ids:
            invoice_html, msg = get_invoice_for_invoiceid(curr_sess, auth_token, invoiceID)

            logging.info(f"msg"+str( msg)  )
            if msg != 'ok':
                logging.info('ok'+str(msg) )
                inv_status.append(f'InvoiceID:{invoiceID} - ERROR INVOICE FETCH PORTAL ISSUE')
            else:
                invoice_html_render, msg = format_html(curr_sess, invoice_html)
                if msg != 'ok':
                    logging.info('html'+str(msg) )
                    inv_status.append(f'InvoiceID:{invoiceID} - ERROR INVOICE FETCH PORTAL ISSUE')
                    continue
                # Write HTML invoice to S3
                html_status, html_s3link = save_file(invoice_html_render.encode('utf-8'), f'{pnr}-{invoiceID}.html')

                if html_status:
                    html_links.append(html_s3link)

        if len(html_links) > 0:
            return {
                "success": True,
                "message": "FILE SAVED TO S3",
                "data": {'s3_link': html_links, 'airline': 'indigo'}
            }
        
        logging.info(f"html_links" +str(html_links) +str(inv_status) +str(invoice_ids) )
        return {
            "success": False,
            "message": "NO RECORD FOUND",
            "data": {}
        }

    except Exception as e:
        logging.info(e)
        return {
            "success": False,
            "message": "MESSAGE ERROR",
            "data": {}
        }

def save_files_locally(files, base_path="downloaded_tickets"):
    """Save files to local directory"""
    os.makedirs(base_path, exist_ok=True)
    saved_paths = []
    
    for file in files:
        filename = os.path.basename(file)
        destination = os.path.join(base_path, filename)
        with open(destination, 'wb') as f:
            f.write(file)
        logging.info(f"Saved file locally: {destination}")
        saved_paths.append(destination)
    
    return saved_paths

def setup_chrome_options(download_folder):
    """
    Sets up Chrome options for downloading PDFs with improved driver automation support.
    """
    print("Creating Selenium WebDriver instance...")
    
    # Configure Chrome options
    options = Options()
    prefs = {
        "download.default_directory": download_folder,
        "download.prompt_for_download": False,
        "download.directory_upgrade": True,
        "safebrowsing.enabled": True,
        "credentials_enable_service": False,
        "profile.password_manager_enabled": False
    }
    options.add_experimental_option("prefs", prefs)
    options.add_experimental_option("excludeSwitches", ['enable-automation', 'enable-logging'])
    options.add_argument("--disable-popup-blocking")
    options.add_argument("--window-size=1920,1400")
    options.add_argument('--disable-gpu')
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument("--disable-blink-features=AutomationControlled")

    try:
        # First attempt: Auto-detect and install matching ChromeDriver
        chromedriver_autoinstaller.install()
        driver = webdriver.Chrome(options=options)
        driver.implicitly_wait(10)
        print("Successfully initialized Chrome driver with auto-installer")
        return driver
    except Exception as auto_error:
        print(f"Auto-installer failed: {auto_error}")
        try:
            # Second attempt: Manual version detection
            chrome_version = chromedriver_autoinstaller.get_chrome_version()
            print(f"Detected Chrome version: {chrome_version}")
            
            # Install matching driver
            service = Service(ChromeDriverManager(version=chrome_version).install())
            driver = webdriver.Chrome(service=service, options=options)
            driver.implicitly_wait(10)
            print(f"Successfully initialized Chrome driver with version {chrome_version}")
            return driver
        except Exception as manual_error:
            print(f"Manual installation failed: {manual_error}")
            raise Exception(f"Failed to initialize Chrome driver: {manual_error}")

def save_file(content, filename):
    """Save content locally"""
    file_path = 'downloaded_tickets/'
    os.makedirs(file_path, exist_ok=True)
    full_path = os.path.join(file_path, filename)

    # Write content based on type
    mode = 'wb' if isinstance(content, bytes) else 'w'
    with open(full_path, mode) as f:
        f.write(content)

    logging.info(f"File saved locally: {full_path}")
    return True, full_path

def save_html_locally(html_content, filename, base_path="downloaded_tickets"):
    """Save HTML content to local directory"""
    os.makedirs(base_path, exist_ok=True)
    file_path = os.path.join(base_path, filename)
    
    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(html_content)
    
    logging.info(f"Saved HTML file locally: {file_path}")
    return True, file_path

def indigo_scraper(ticket_pnr, ssr_email_list, count=0, PORT=24000):
    try:
        logging.info(f"Starting indigo scraper for PNR: {ticket_pnr}")
        logging.info(f"SSR Email List: {ssr_email_list}")
        
        for ssr_email in ssr_email_list:
            logging.info(f"Trying with SSR Email: {ssr_email}")
            response = indigo_scraper_pnr(ticket_pnr, ssr_email, count, PORT)
            
            if response['success']:
                return response
            
            logging.warning(f"Failed for SSR Email: {ssr_email}. Error: {response['message']}")
        
        return {
            "success": False, 
            "message": "Failed with all SSR emails",
            "data": {}
        }
    
    except Exception as e:
        logging.error(f"Error in indigo_scraper: {str(e)}")
        return {
            "success": False,
            "message": str(e),
            "data": {}
        }

if __name__ == '__main__':
    # Test data for debugging
    test_data = {
        'Ticket/PNR': 'RZ429P',  # Replace with actual test PNR
        'SSR_Emails': ['sbtinvoice@gail.co.in'],  # Replace with actual test email
        'Port': 10020
    }
    
    print("Starting debug run...")
    print("Test data:", json.dumps(test_data, indent=2))
    
    # Create necessary folders
    os.makedirs("downloaded_tickets", exist_ok=True)
    
    # Run the scraper
    result = indigo_scraper(
        test_data['Ticket/PNR'],
        test_data['SSR_Emails'],
        count=0,
        PORT=test_data['Port']
    )
    
    print("\nScraping Results:")
    print("Success:", result["success"])
    print("Message:", result["message"])
    print("Data:", json.dumps(result["data"], indent=2))
