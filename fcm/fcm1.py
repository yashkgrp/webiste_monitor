from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from datetime import datetime
import chromedriver_autoinstaller
import allure
import pandas as pd
import pytest
import time
import logging
import os
import sys
import json
from seleniumwire import webdriver  # Use Selenium Wire for API interception

# Configure logging
logging.basicConfig(filename="testlog.log", level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

def setup_chrome_driver():
    """Initialize Selenium WebDriver with automatic version detection"""
    try:
        logger.info('Starting Chrome browser setup')
        
        # Selenium Wire specific options
        seleniumwire_options = {
            'verify_ssl': False,
            'suppress_connection_errors': True,
            'detect_proxy': False,
            'disable_encoding': True,  # Important for request modification
            'enable_har': True,
            'ignore_http_methods': ['OPTIONS'],
            'request_storage': 'memory'  # Store requests in memory
        }
        
        options = Options()
        prefs = {
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
            driver = webdriver.Chrome(options=options, seleniumwire_options=seleniumwire_options)
            driver.implicitly_wait(10)
            logger.info("Successfully initialized Chrome driver with auto-installer")
            return driver
            
        except Exception as auto_error:
            logger.warning(f"Auto-installer failed: {auto_error}")
            # Fallback to manual version detection
            try:
                chrome_version = chromedriver_autoinstaller.get_chrome_version()
                logger.info(f"Detected Chrome version: {chrome_version}")
                
                service = Service(ChromeDriverManager(version=chrome_version).install())
                driver = webdriver.Chrome(service=service, options=options, seleniumwire_options=seleniumwire_options)
                driver.implicitly_wait(10)
                logger.info(f"Successfully initialized Chrome driver with version {chrome_version}")
                return driver
                
            except Exception as manual_error:
                logger.error(f"Manual installation failed: {manual_error}")
                raise Exception(f"Failed to initialize Chrome driver: {manual_error}")
                
    except Exception as e:
        logger.error(f"Chrome driver setup failed: {e}")
        raise

# Update the fixture to use the new setup function
@pytest.fixture(scope="session", autouse=True)
def setup_browser():
    """Sets up Selenium WebDriver and opens the login page."""
    global driver
    driver = setup_chrome_driver()
    driver.request_interceptor = interceptor
    driver.response_interceptor = response_interceptor
    driver.get(url)
    driver.maximize_window()
    yield
    driver.quit()

# :white_check_mark: URLs
url = "https://bcd.finkraft.ai/auth/signin"

# :white_check_mark: Initialize test results
test_results = []

# :white_check_mark: Request Interceptor to Modify API Payload
def interceptor(request):
    if request.method == "POST" and "api/auth/user/internal/create" in request.url:
        print(":pushpin: Intercepted API Call")
        print(f"URL: {request.url}")
        print(f"Method: {request.method}")
        try:
            original_body = request.body.decode('utf-8')
            print(f"Original Request Body: {original_body}")

            # Ensure it's valid JSON
            payload = json.loads(original_body)
            print(f"Original Parsed Payload: {payload}")

            # Modify the payload
            payload["testMode"] = True
            print(f"Modified Payload: {payload}")

            # Convert back to JSON string
            modified_body = json.dumps(payload).encode('utf-8')

            # Assign modified body
            request.body = modified_body  # Encoding it properly
            print(f"Final Modified Request Body: {request.body}")
            
            # Ensure the headers reflect the new body length
            
            

        except Exception as e:
            print(f":x: Error modifying payload: {e}")
            

        except Exception as e:
            print(f":x: Error modifying payload: {e}")

def response_interceptor(request, response):
    
    if request.method == "POST" and "api/auth/user/internal/create" in request.url:
        print("\n🔍 Intercepting API Call")
        try:
            # Get and decode original body
            original_body = request.body.decode('utf-8')
            print(f"Original Body: {original_body}")
            
            # Parse and modify payload
            payload = json.loads(original_body)
            payload["testMode"] = True
            
            # Convert to JSON string and encode to bytes
            modified_body = json.dumps(payload, separators=(',', ':'), ensure_ascii=False).encode('utf-8')
            
            # Update request body and headers
            request.body = modified_body
            request.headers.update({
                'Content-Type': 'application/json; charset=utf-8',
                'Content-Length': str(len(modified_body))
            })
            
            print(f"Modified Body: {modified_body.decode('utf-8')}")
            print(f"Updated Headers: {dict(request.headers)}")
            
            # Return the modified request
            return request

        except Exception as e:
            print(f"❌ Error in interceptor: {str(e)}")
            logger.error(f"Interceptor error: {str(e)}", exc_info=True)
            return request

# :white_check_mark: Attach the interceptor


@allure.title("Client View")
def test_login():
    """Logs in after opening the browser and asking for credentials."""
    driver.get(url)
    time.sleep(2)  # Ensure the page is fully loaded before asking for credentials
    try:
        # :white_check_mark: Ask for email
        email = "sushmitha@kgrp.in"
        # :white_check_mark: Enter email
        email_input = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.XPATH, '//*[@id="basic"]/div[1]/div/div/div/div/div/div/input'))
        )
        email_input.clear()
        email_input.send_keys(email)
        time.sleep(1)
        # :white_check_mark: Click 'Sign in with password' button
        driver.find_element(By.XPATH, '//*[@id="basic"]/div[2]/button').click()
        time.sleep(2)
        # :white_check_mark: Check for login failure popup
        try:
            popup_element = WebDriverWait(driver, 5).until(
                EC.presence_of_element_located((By.XPATH, "//div[contains(@class, 'ant-input-status-error')]"))
            )
            popup_message = popup_element.text.strip()
            print(f":x: Login failed for {email}: {popup_message}")
            # :white_check_mark: Capture Screenshot
            capture_screenshot(email, "failed_login")
            # :white_check_mark: Log Error
            test_results.append({"Email": email, "Status": "Login Failed"})
            return
        except:
            pass  # No popup, assume login was successful
        # :white_check_mark: Ask for password
        password = "euMgvJFL"
        # :white_check_mark: Enter password
        password_field = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.XPATH, '//*[@id="basic"]/div[2]/div/div/div/div/div/div/input'))
        )
        password_field.send_keys(password)
        # :white_check_mark: Click login button
        login = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.XPATH, '//*[@id="basic"]/div[3]/button'))
        )
        login.click()
        time.sleep(10)  # Wait for redirection
        if 'dashboard' in driver.current_url:
            print(f":white_check_mark: Login successful for {email}")
            test_results.append({"Email": email, "Status": "Success - Dashboard Loaded"})
            time.sleep(5)
        # Add members session
        print("Member session for adding new member to respective workspace")
        # Click on Member section
        driver.find_element(By.XPATH, '//*[@id="root"]/div/div[1]/div/div/div[2]/div[2]').click()
        time.sleep(2)
        # Click on Add Member Button
        driver.find_element(By.XPATH, '//*[@id="root"]/div/div[2]/div/div/div/div[1]/div[2]/div[1]/div/button').click()
        time.sleep(1)
        # Enter Name
        name = "mayuri"
        WebDriverWait(driver, 10).until(EC.visibility_of_element_located((By.CSS_SELECTOR, 'input[placeholder="Name"]'))).send_keys(name)
        time.sleep(2)
        # Enter Email
        emailid = "sushmitha@kgrp.in"
        WebDriverWait(driver, 10).until(EC.visibility_of_element_located((By.CSS_SELECTOR, 'input[placeholder="Email"]'))).send_keys(emailid)
        time.sleep(2)
        # Search Workspace
        workspace_name = "Airbus"
        search_box = WebDriverWait(driver, 10).until(EC.element_to_be_clickable((By.CSS_SELECTOR, 'input[placeholder="Search Workspace"]')))
        search_box.send_keys(workspace_name)
        time.sleep(2)
        driver.find_element(By.XPATH, "(//p[contains(@class, 'sc-blHHSb kwGAvL')])[1]").click()
        time.sleep(1)
        driver.find_element(By.XPATH, "(//label[contains(@class, 'ant-checkbox-wrapper')])[1]").click()
        # Select Role
        dropdown = WebDriverWait(driver, 10).until(EC.element_to_be_clickable((By.XPATH, '/html/body/div[4]/div/div[2]/div/div[1]/div/div[2]/div/div[4]/div/div[1]/div[2]/div/div/span/span[2]')))
        dropdown.click()
        time.sleep(1)
        driver.find_element(By.XPATH, "//div[contains(@class, 'ant-select-item-option') and text()='User']").click()
        time.sleep(2)
        # Add Member
        driver.find_element(By.XPATH, '/html/body/div[4]/div/div[2]/div/div[1]/div/div[2]/div/div[5]/button[2]').click()
        time.sleep(3)
        # API Request Interception
        # :white_check_mark: API Request Interception and Logging
        for request in driver.requests:
            if "api/auth/user/internal/create" in request.url:
                print("\n=== Request Details ===")
                print(f"URL: {request.url}")
                print(f"Method: {request.method}")
                print(f"Headers: {dict(request.headers)}")
                try:
                    body = request.body.decode('utf-8')
                    print(f"Request Body: {body}")
                except:
                    print("Could not decode request body")
                    
                if request.response:
                    print("\n=== Response Details ===")
                    print(f"Status Code: {request.response.status_code}")
                    print(f"Response Headers: {dict(request.response.headers)}")
                    try:
                        response_body = request.response.body.decode('utf-8')
                        print(f"Response Body: {response_body}")
                    except:
                        print("Could not decode response body")
                print("=====================\n")
                
                if request.response and request.response.status_code == 200:
                    print(f":white_check_mark: Member/User added successfully for {emailid}")
                    test_results.append({"Email": emailid, "Status": "Success - User added"})
                else:
                    status_code = request.response.status_code if request.response else "No response"
                    print(f":x: Failed to add user. Status code: {status_code}")
                    test_results.append({"Email": emailid, "Status": f"Failed - API Status {status_code}"})
                break
        
        else:
            print(f":x: API Not Triggered for {emailid}")
            test_results.append({"Email": emailid, "Status": "Failed - API Not Triggered"})
        time.sleep(30000)
    except Exception as e:
        print(f":x: Error logging in for {email}: {e}")
        test_results.append({"Email": email, "Status": f"Login Failed - {e}"})
        capture_screenshot(email, "error")

def capture_screenshot(email, error_type):
    """Captures and saves screenshots for debugging."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    screenshot_dir = "screenshots"
    os.makedirs(screenshot_dir, exist_ok=True)
    screenshot_path = os.path.join(screenshot_dir, f"{error_type}_{email.replace('@', '_')}_{timestamp}.png")
    driver.save_screenshot(screenshot_path)
    print(f":camera_with_flash: Screenshot saved: {screenshot_path}")

@pytest.fixture(scope="session", autouse=True)
def save_results():
    """Saves test results to CSV file after all tests are executed."""
    yield  # Wait until all tests are done
    df = pd.DataFrame(test_results)
    df.to_csv("test_results.csv", index=False)
    print(":white_check_mark: Test results saved to 'test_results.csv'")