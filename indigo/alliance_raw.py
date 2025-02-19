import logging
import time
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from PIL import Image
from io import BytesIO
import base64
import os
import chromedriver_autoinstaller
from selenium.webdriver.chrome.options import Options
import json
import shutil
import requests
from html import unescape

# Configure the logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('alliance_scraper.log'),
        logging.StreamHandler()  # This will print logs to console as well
    ]
)

def get_captcha_base64(data):
    """
    Get captcha result from base64 string
    """
    response = requests.post('http://2captcha.com/in.php', data={
        'key': "53c6618ef94876268350965f59bf3e50",
        'method': 'base64',
        'body': data,
        'json': 1,
        'regsense': 1
    }).json()

    captcha_id = response['request']

    # wait for captcha to be solved
    for i in range(1,4,1):
        time.sleep(10)
        response = requests.post('http://2captcha.com/res.php', data={
            'key': "53c6618ef94876268350965f59bf3e50",
            'action': 'get',
            'id': int(captcha_id)
        }).text
        
        if response == 'ERROR_CAPTCHA_UNSOLVABLE':
            print("captcha unsolvable error")
            return '000000'

        if '|' in response:
            _, captcha_text = unescape(response).split('|')
            return (captcha_id, captcha_text)

def mark_good(captcha_id):
    """
    Mark captcha as good
    """
    resp = requests.post('http://2captcha.com/res.php', data={
        'key': "53c6618ef94876268350965f59bf3e50",
        'action': 'reportgood',
        'id': int(captcha_id)
    })

    if resp.status_code == 200 and resp.text == 'OK_REPORT_RECORDED':
        print('Good captcha reported')
        return True
    else:
        print('Failed to report good captcha')
        return False

def mark_bad(captcha_id):
    """
    Mark captcha as bad
    """
    resp = requests.post('http://2captcha.com/res.php', data={
        'key': "53c6618ef94876268350965f59bf3e50",
        'action': 'reportbad',
        'id': int(captcha_id)
    })

    if resp.status_code == 200 and resp.text == 'OK_REPORT_RECORDED':
        print('Bad captcha reported')
        return True
    else:
        print('Failed to report bad captcha')
        return False

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
    # options.add_argument("--headless=new")
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

def take_screenshot(driver, screenshot_name, screenshots_folder):
    """Take and save a screenshot locally"""
    try:
        os.makedirs(screenshots_folder, exist_ok=True)
        screenshot_path = os.path.join(screenshots_folder, f"{screenshot_name}.png")
        driver.save_screenshot(screenshot_path)
        logging.info(f"Screenshot saved: {screenshot_path}")
        return screenshot_path
    except Exception as e:
        logging.error(f"Error taking screenshot: {e}")
        return None

def save_files_locally(files, base_path="downloaded_tickets"):
    """Save files to local directory"""
    os.makedirs(base_path, exist_ok=True)
    saved_paths = []
    
    for file in files:
        filename = os.path.basename(file)
        destination = os.path.join(base_path, filename)
        shutil.copy2(file, destination)
        logging.info(f"Saved file locally: {destination}")
        saved_paths.append(destination)
    
    return saved_paths

def attempt_login(driver, date, pnr, download_folder, screenshots_folder):
    try:
        url = 'https://allianceair.co.in/gst/'
        logging.info(f"Navigating to URL: {url}")
        driver.get(url)
        time.sleep(5)

        logging.info(f"Filling form for PNR: {pnr}, Date: {date}")
        driver.find_element(By.ID, "txtDOJ").click()
        driver.find_element(By.ID, "txtDOJ").clear()
        driver.find_element(By.ID, "txtDOJ").send_keys(date)
        time.sleep(3)
        driver.find_element(By.ID, "txtPNR").click()
        driver.find_element(By.ID, "txtPNR").clear()
        driver.find_element(By.ID, "txtPNR").send_keys(pnr)
        time.sleep(3)

        # Capture and solve CAPTCHA
        captcha_image_element = driver.find_element(By.ID, "Image1")
        captcha_image_data = captcha_image_element.screenshot_as_png

        image = Image.open(BytesIO(captcha_image_data))
        buffer = BytesIO()
        image.save(buffer, format="PNG")
        base64_image = base64.b64encode(buffer.getvalue()).decode("utf-8")

        logging.info("Attempting to solve CAPTCHA")
        captcha_result = get_captcha_base64(base64_image)
        
        if captcha_result == '000000':
            logging.error("CAPTCHA unsolvable")
            return False, None, take_screenshot(driver, f"captcha_error_{pnr}", screenshots_folder)
            
        captcha_id, captcha_text = captcha_result
        logging.info(f"CAPTCHA solved: {captcha_text}")
        captcha_text_cap = captcha_text.upper()

        # Fill in CAPTCHA and submit
        driver.find_element(By.ID, "txtVerificationCodeNew").click()
        driver.find_element(By.ID, "txtVerificationCodeNew").clear()
        driver.find_element(By.ID, "txtVerificationCodeNew").send_keys(captcha_text_cap)
        button = driver.find_element(By.XPATH, '//*[@id="btnSearch"]')
        button.click()
        time.sleep(5)

        try:
            driver.find_element(By.ID, "lnkdownload").click()
            filename = driver.find_element(By.XPATH, '//*[@id="lbl"]').text
            if filename:
                logging.info("File downloaded successfully")
                mark_good(captcha_id)  # Mark CAPTCHA as correctly solved
                screenshot_path = take_screenshot(driver, f"success_{pnr}", screenshots_folder)
                
                # Wait for file download
                time.sleep(5)
                downloaded_file = os.path.join(download_folder, filename + ".pdf")
                
                if os.path.exists(downloaded_file):
                    logging.info(f"Downloaded file found: {downloaded_file}")
                    return True, downloaded_file, screenshot_path
                else:
                    logging.warning("Downloaded file not found")
                    return False, None, screenshot_path
            else:
                mark_bad(captcha_id)  # Mark CAPTCHA as incorrect
                logging.warning("Download link not found")
                screenshot_path = take_screenshot(driver, f"download_link_not_found_{pnr}", screenshots_folder)
                return False, None, screenshot_path

        except Exception as e:
            mark_bad(captcha_id)  # Mark CAPTCHA as incorrect
            logging.error(f"Error while downloading file: {e}")
            screenshot_path = take_screenshot(driver, f"error_download_{pnr}", screenshots_folder)
            return False, None, screenshot_path

    except Exception as e:
        logging.error(f"Error during login or form submission: {e}")
        screenshot_path = take_screenshot(driver, f"error_login_{pnr}", screenshots_folder)
        return False, None, screenshot_path

def alliance_scraper(data):
    max_attempts = 3
    try:
        vendor = data['Vendor']
        airline = 'alliance'
        pnr = data['Ticket/PNR']
        date = data['Transaction_Date']
        success = False
        
        # Setup folders
        download_folder = os.path.join(os.getcwd(), "downloads")
        screenshots_folder = os.path.join(os.getcwd(), "screenshots")
        os.makedirs(download_folder, exist_ok=True)
        os.makedirs(screenshots_folder, exist_ok=True)
        
        logging.info(f"Starting scraper for PNR: {pnr}, Vendor: {vendor}")

        for attempt in range(max_attempts):
            logging.info(f"Attempt {attempt + 1} for PNR: {pnr}")
            driver = setup_chrome_options(download_folder)
            status, downloaded_file, screenshot_path = attempt_login(driver, date, pnr, download_folder, screenshots_folder)

            if status and downloaded_file:
                success = True
                logging.info(f"Scraper successful for PNR: {pnr}")
                # Save file locally
                local_paths = save_files_locally([downloaded_file])
                return {
                    "success": True,
                    "message": "Files saved locally",
                    "data": {
                        'local_paths': local_paths,
                        'airline': airline,
                        'screenshot_path': screenshot_path
                    }
                }
            else:
                logging.warning(f"Attempt {attempt + 1} failed for PNR: {pnr}. Retrying...")

        if not success:
            logging.error(f"Failed to download files after {max_attempts} attempts for PNR: {pnr}")
            return {
                "success": False,
                "message": "Failed to download files",
                "data": {
                    'screenshot_path': screenshot_path
                }
            }
    except Exception as e:
        logging.critical(f"Error in alliance_scraper function: {e}")
        return {
            "success": False,
            "message": str(e),
            "data": {}
        }

if __name__ == '__main__':
    # Test data for debugging
    test_data = {
        'Ticket/PNR': 'P6CZDL',  # Replace with actual test PNR
        'Transaction_Date': '06-06-2024',  # Replace with actual test date
        'Vendor': 'ALLIANCE AIR'
    }
    
    print("Starting debug run...")
    print("Test data:", json.dumps(test_data, indent=2))
    
    # Run the scraper
    result = alliance_scraper(test_data)
    
    print("\nScraping Results:")
    print("Success:", result["success"])
    print("Message:", result["message"])
    print("Data:", json.dumps(result["data"], indent=2))