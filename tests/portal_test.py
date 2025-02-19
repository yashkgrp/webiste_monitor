from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from datetime import datetime
import allure
import pandas as pd
import pytest
import time
import logging
import os
import sys
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
import chromedriver_autoinstaller

# Set up logging
logging.basicConfig(filename="testlog.log", level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# Initialize test results
test_results = []

# URLs
url = "https://qatarnew.finkraft.ai"
reg_url = "https://qatarnew.finkraft.ai/register"
login_url = "https://qatarnew.finkraft.ai/login"

# Registration credentials
reg_credentials = [
    {"name": "Sonu", "email": "monica@yopmail.com", "business_type": "CORPORATE"},
    {"name": "Sonu", "email": "snjknopmailcom", "business_type": "CARGO"},
    {"name": "Sonu", "email": "level+15@yopmail.com", "business_type": "CORPORATE"},
]

COMPANY_DETAILS = {
    "name": "Test Company",
    "website": "www.testcompany.com",
    "pan": "ADHSJ7182S"
}

TAX_MANAGER_DETAILS = {
    "name": "John Doe",
    "email": "john@example.com",
    "phone": "1234567890",
    "linkedin": "linkedin.com/johndoe"
}

TRAVEL_CONTACT_DETAILS = {
    "name": "Jane Doe",
    "email": "jane@example.com",
    "phone": "9876543210",
    "linkedin": "linkedin.com/janedoe"
}

def setup_chrome_driver(download_folder=None):
    """Initialize Chrome WebDriver with automatic version detection"""
    try:
        options = Options()
        if download_folder:
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
            # Auto-detect and install matching ChromeDriver
            chromedriver_autoinstaller.install()
            driver = webdriver.Chrome(options=options)
            driver.implicitly_wait(10)
            logging.info("Successfully initialized Chrome driver with auto-installer")
            
        except Exception as auto_error:
            logging.warning(f"Auto-installer failed: {auto_error}")
            # Fallback to manual version detection
            try:
                chrome_version = chromedriver_autoinstaller.get_chrome_version()
                logging.info(f"Detected Chrome version: {chrome_version}")
                
                service = Service(ChromeDriverManager(version=chrome_version).install())
                driver = webdriver.Chrome(service=service, options=options)
                driver.implicitly_wait(10)
                logging.info(f"Successfully initialized Chrome driver with version {chrome_version}")
                
            except Exception as manual_error:
                logging.error(f"Manual installation failed: {manual_error}")
                raise Exception(f"Failed to initialize Chrome driver: {manual_error}")

        # Test the driver
        driver.get("about:blank")
        return driver

    except Exception as e:
        logging.error(f"Chrome driver setup failed: {e}")
        raise Exception(f"Failed to setup Chrome driver: {e}")

# Setup WebDriver
@pytest.fixture(scope="session", autouse=True)
def setup_browser():
    global driver
    driver = setup_chrome_driver()
    driver.maximize_window()
    yield
    driver.quit()

def safe_send_keys(element, value):
    """Helper function to clear field using backspace and send keys safely"""
    try:
        # Get current value length and clear using backspace
        current_value = element.get_attribute('value')
        if current_value:
            # Send backspace key multiple times with small delays
            for _ in range(len(current_value) + 2):  # +2 for safety
                element.send_keys(Keys.BACKSPACE)
                time.sleep(0.1)  # Small delay between backspaces
        
        # Additional wait after clearing
        time.sleep(2)
        
        # Verify field is empty
        if element.get_attribute('value'):
            # Try one more time with longer backspace sequence
            for _ in range(20):  # Extra backspaces for good measure
                element.send_keys(Keys.BACKSPACE)
                time.sleep(0.1)
        
        # Send new value
        element.send_keys(value)
        return True
        
    except Exception as e:
        logging.error(f"Error sending keys: {str(e)}")
        return False

@allure.title("Client View")
def test_registration_with_details(username, password):
    """
    Execute registration test with provided credentials and hardcoded details
    """
    driver.get(login_url)
    time.sleep(2)

    # Login
    username_field = driver.find_element(By.XPATH, '//*[@id="registration-page"]/div[2]/div/div[2]/div/div/form/div[1]/input')
    password_field = driver.find_element(By.XPATH, '//*[@id="registration-page"]/div[2]/div/div[2]/div/div/form/div[2]/span/input')
    
    safe_send_keys(username_field, username)
    time.sleep(1)
    safe_send_keys(password_field, password)
    time.sleep(1)

    driver.find_element(By.XPATH, '//*[@id="registration-page"]/div[2]/div/div[2]/div/div/form/button').click()
    print(f"✅ Login attempt for {username}")

    time.sleep(5)

    if "app" in driver.current_url:
        print(f"✅ Login successful for {username}")
        test_results.append({"Email": username, "Status": "Success - Login"})

        time.sleep(1)            
                    
        try:
            # Company Details
            name_field = driver.find_element(By.ID, 'name')
            website_field = driver.find_element(By.ID, 'Company Website')
            pan_field = driver.find_element(By.ID, 'PAN Number')
            
            safe_send_keys(name_field, COMPANY_DETAILS['name'])
            safe_send_keys(website_field, COMPANY_DETAILS['website'])
            safe_send_keys(pan_field, COMPANY_DETAILS['pan'])
            
            driver.find_element(By.XPATH, '//*[@id="root"]/div/div[2]/div[2]/div/div[2]/div/form/button').click()
            print("✅ Company details done")

            time.sleep(6)

            # Tax Manager Details
            tax_name = driver.find_element(By.ID, 'Name')
            tax_email = driver.find_element(By.ID, 'Email')
            tax_mobile = driver.find_element(By.ID, 'Mobile')
            tax_linkedin = driver.find_element(By.ID, 'LinkedIn profile link')
            
            safe_send_keys(tax_name, TAX_MANAGER_DETAILS['name'])
            safe_send_keys(tax_email, TAX_MANAGER_DETAILS['email'])
            safe_send_keys(tax_mobile, TAX_MANAGER_DETAILS['phone'])
            safe_send_keys(tax_linkedin, TAX_MANAGER_DETAILS['linkedin'])
            
            driver.find_element(By.XPATH, '//*[@id="root"]/div/div[2]/div[2]/div/div[2]/div/form/div[7]/button[2]').click()
            time.sleep(5)

            # Travel Contact Details
            travel_name = driver.find_element(By.ID, 'name')
            travel_email = driver.find_element(By.ID, 'Email')
            travel_mobile = driver.find_element(By.ID, 'Mobile')
            travel_linkedin = driver.find_element(By.ID, 'LinkedIn profile link')
            
            safe_send_keys(travel_name, TRAVEL_CONTACT_DETAILS['name'])
            safe_send_keys(travel_email, TRAVEL_CONTACT_DETAILS['email'])
            safe_send_keys(travel_mobile, TRAVEL_CONTACT_DETAILS['phone'])
            safe_send_keys(travel_linkedin, TRAVEL_CONTACT_DETAILS['linkedin'])
            time.sleep(4)
            decision = "Next"
            if decision == "Next" :
                next = driver.find_element(By.XPATH , '//*[@id="root"]/div/div[2]/div[2]/div/div[2]/div/form/div[7]/button[2]').click()
            else :
                back = driver.find_element(By.XPATH , '//*[@id="root"]/div/div[2]/div[2]/div/div[2]/div/form/div[7]/button[1]').click()
            time.sleep(5)
            preview = driver.find_element(By.XPATH, '//*[@id="root"]/div/div[2]/div[2]/div/div[2]/div/div[2]/button').click()
            time.sleep(5)

            # Preview and submit


        except Exception as e:
            print(f"Error occurred: {str(e)}")   
            test_results.append({"CompanyName": COMPANY_DETAILS['name'], "Status": "Failed - Company Name or PAN already exist"}) 
            handle_error({"email": username}, e)
    else:
        print(f"❌ Login failed for {username}")
        capture_screenshot({"email": username}, "login_failed")
        test_results.append({"Email": username, "Status": "Failed - Login Issue"})    

def handle_error(username, error):
    """Handles errors by logging and saving screenshots."""
    capture_screenshot(username, "error")
    logging.error(f"❌ Error for {username['email']}: {error}")
    print(f"❌ Error for {username['email']}. Screenshot saved.")

    test_results.append({"Email": username["email"], "Status": f"Error - {error}"})


def capture_screenshot(username, error_type):
    """Captures a screenshot for debugging."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    screenshot_dir = "screenshots"
    os.makedirs(screenshot_dir, exist_ok=True)
    screenshot_path = os.path.join(screenshot_dir, f"{error_type}_{username['email'].replace('@', '_').replace('.', '_')}_{timestamp}.png")
    
    driver.save_screenshot(screenshot_path)
    print(f"📸 Screenshot saved: {screenshot_path}")

# def verify_registration_details(username, password):
#     """Verify the submitted registration details by logging in again"""
#     try:
#         driver = setup_chrome_driver()
#         driver.maximize_window()
#         driver.get(url)
#         time.sleep(1)

#         # Click login button
#         login = driver.find_element(By.XPATH, '//*[@id="root"]/div/div/div[1]/header/div/div[2]/button[2]').click()
#         time.sleep(3)

#         # Login with credentials
#         username_field = driver.find_element(By.XPATH, '//*[@id="registration-page"]/div[2]/div/div[2]/div/div/form/div[1]/input')
#         password_field = driver.find_element(By.XPATH, '//*[@id="registration-page"]/div[2]/div/div[2]/div/div/form/div[2]/span/input')
        
#         safe_send_keys(username_field, username)
#         safe_send_keys(password_field, password)
#         time.sleep(5)

#         # Click sign in
#         driver.find_element(By.XPATH, '//*[@id="registration-page"]/div[2]/div/div[2]/div/div/form/button').click()
#         time.sleep(20)

#         # Go to user details
#         driver.find_element(By.XPATH, '//*[@id="root"]/div/div[1]/div/div[1]/ul/li[2]/a').click()
#         time.sleep(2)
        
#         # Verify each card section
#         verification_results = {
#             'company': {},
#             'tax_manager': {},
#             'travel_contact': {}
#         }

#         # Company Card Verification
#         Company_card = driver.find_element(By.XPATH, '//*[@id="root"]/div/div[2]/div[2]/div/div[1]/div[1]')
#         company_edit = driver.find_element(By.XPATH, '//*[@id="root"]/div/div[2]/div[2]/div/div[1]/div[1]/div[1]/button').click()
#         company_edit_form = driver.find_element(By.XPATH, '/html/body/div[4]/div/div[2]/div/div[1]/div')
        
#         # Company Name
#         company_name = company_edit_form.find_element(By.XPATH, '/html/body/div[4]/div/div[2]/div/div[1]/div/div[2]/form/div/div[1]/input')
#         current_name = company_name.get_attribute("value")
#         verification_results['company']['name'] = {
#             'expected': COMPANY_DETAILS['name'],
#             'actual': current_name,
#             'match': current_name == COMPANY_DETAILS['name']
#         }
#         print(f"Company Name - Current: {current_name}, Expected: {COMPANY_DETAILS['name']}")
        
#         # Company Website
#         company_web = company_edit_form.find_element(By.XPATH, '/html/body/div[4]/div/div[2]/div/div[1]/div/div[2]/form/div/div[2]/input')
#         current_website = company_web.get_attribute("value")
#         verification_results['company']['website'] = {
#             'expected': COMPANY_DETAILS['website'],
#             'actual': current_website,
#             'match': current_website == COMPANY_DETAILS['website']
#         }
#         print(f"Company Website - Current: {current_website}, Expected: {COMPANY_DETAILS['website']}")

#         # Company PAN
#         company_pan = company_edit_form.find_element(By.XPATH, '/html/body/div[4]/div/div[2]/div/div[1]/div/div[2]/form/div/div[3]/input')
#         current_pan = company_pan.get_attribute("value")
#         verification_results['company']['pan'] = {
#             'expected': COMPANY_DETAILS['pan'],
#             'actual': current_pan,
#             'match': current_pan == COMPANY_DETAILS['pan']
#         }
#         print(f"Company PAN - Current: {current_pan}, Expected: {COMPANY_DETAILS['pan']}")

#         # Close company edit form
#         driver.find_element(By.XPATH, '/html/body/div[4]/div/div[2]/div/div[1]/div/div[3]/button[1]').click()
#         time.sleep(2)

#         # Print verification summary
#         print("\n=== Verification Results ===")
#         for section, fields in verification_results.items():
#             print(f"\n{section.upper()} DETAILS:")
#             for field, result in fields.items():
#                 match_status = "✅" if result['match'] else "❌"
#                 print(f"{field}: {match_status}")
#                 print(f"  Expected: {result['expected']}")
#                 print(f"  Actual: {result['actual']}")

#         # Add verification results to test_results
#         test_results.append({
#             "Email": username,
#             "Status": "Verification Complete",
#             "Verification": verification_results
#         })

#         return verification_results

#     except Exception as e:
#         print(f"Verification failed: {str(e)}")
#         if 'driver' in locals():
#             capture_screenshot({"email": username}, "verification_error")
#         test_results.append({
#             "Email": username,
#             "Status": f"Verification Failed - {str(e)}"
#         })
#         return None
#     finally:
#         if 'driver' in locals():
#             driver.quit()

@pytest.fixture(scope="session", autouse=True)
def save_results():
    """Save test results to CSV file after all tests are executed."""
    yield  # Wait until all tests are done
    df = pd.DataFrame(test_results)
    df.to_csv("test_results.csv", index=False)
    print("✅ Test results saved to 'test_results.csv'")

if __name__ == "__main__":
    username = "temp@yopmail.com"
    password = "kKkgRK72"
    
    try:
        # First run the registration
        driver = setup_chrome_driver()
        driver.maximize_window()
        test_registration_with_details(username, password)
        driver.quit()

        print("\nWaiting 5 seconds before verification...")
        time.sleep(5)

        # Then verify the details
        # verify_registration_details(username, password)

    except Exception as e:
        print(f"Test execution failed: {e}")
    finally:
        # Save results
        df = pd.DataFrame(test_results)
        df.to_csv("test_results.csv", index=False)
        print("✅ Test results saved to 'test_results.csv'")


