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

# ✅ Set up logging
logging.basicConfig(filename="testlog.log", level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# ✅ URLs
url = "https://fcm.finkraft.ai/auth/signin"

# ✅ Initialize test results
test_results = []


@pytest.fixture(scope="session", autouse=True)
def setup_browser():
    """Sets up Selenium WebDriver and opens the login page."""
    global driver
    driver = webdriver.Chrome()
    driver.get(url)
    driver.maximize_window()
    yield
    driver.quit()


@allure.title("Client View")
def test_login():
    """Logs in after opening the browser and asking for credentials."""
    driver.get(url)
    time.sleep(2)  # Ensure the page is fully loaded before asking for credentials

    try:
        # ✅ Ask for email
        email = "sushmitha@kgrp.in"

        # ✅ Enter email
        email_input = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.XPATH, '//*[@id="basic"]/div[1]/div/div/div/div/div/div/input'))
        )
        email_input.clear()
        email_input.send_keys(email)
        time.sleep(1)

        # ✅ Click 'Sign in with password' button
        driver.find_element(By.XPATH, '//*[@id="basic"]/div[2]/button').click()
        time.sleep(2)

        # ✅ Check for login failure popup
        try:
            popup_element = WebDriverWait(driver, 5).until(
                EC.presence_of_element_located((By.XPATH, "//div[contains(@class, 'ant-input-status-error')]"))
            )
            popup_message = popup_element.text.strip()
            print(f"❌ Login failed for {email}: {popup_message}")

            # ✅ Capture Screenshot
            capture_screenshot(email, "failed_login")

            # ✅ Log Error
            test_results.append({"Email": email, "Status": "Login Failed"})
            return

        except:
            pass  # No popup, assume login was successful

        # ✅ Ask for password
        password = "euMgvJFL"

        # ✅ Enter password
        password_field = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.XPATH, '//*[@id="basic"]/div[2]/div/div/div/div/div/div/input'))
        )
        password_field.send_keys(password)

        # ✅ Click login button
        driver.find_element(By.XPATH, '//*[@id="basic"]/div[3]/button').click()

        time.sleep(8)  # Wait for redirection

        if 'dashboard' in driver.current_url:
            print(f"✅ Login successful for {email}")
            test_results.append({"Email": email, "Status": "Success - Dashboard Loaded"})

            time.sleep(5)


        # 1. Add members

        print("Member session for adding new member to respective workspace")

        driver.find_element(By.XPATH ,'//*[@id="root"]/div/div[1]/div/div/div[2]/div[2]').click()
        time.sleep(1)
        add = driver.find_element(By.XPATH , '//*[@id="root"]/div/div[2]/div/div/div/div[1]/div[2]/div[1]/div/button')   
        add = add.click()
        time.sleep(1)
        #name 
        name = "mayuri"
        input_element = WebDriverWait(driver, 10).until(
            EC.visibility_of_element_located((By.CSS_SELECTOR , 'input[placeholder="Name"]'))
        )
        input_element.send_keys(name)

        time.sleep(2)

        # Email
        emailid = "sushu@yopmail.com"
        input_element = WebDriverWait(driver, 10).until(
            EC.visibility_of_element_located((By.CSS_SELECTOR , 'input[placeholder="Email"]'))
        )
        input_element.send_keys(emailid)

        time.sleep(2)

        # Hardcoded workspace name 
        workspace_name = "HALDIA TECH"

        # Find and enter workspace name in the search box
        search_box = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, 'input[placeholder="Search Workspace"]'))
        )
        search_box.clear()  # Clear any existing text
        search_box.send_keys(workspace_name)
        time.sleep(2)  # Allow time for results to load

        # Select the first workspace option directly
        first_workspace = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.XPATH, "(//p[contains(@class, 'sc-blHHSb kwGAvL')])[1]"))
        )
        first_workspace.click()  # Click the first workspace option
        time.sleep(1)  # Wait for the checkbox to become clickable

        # Select the checkbox for the first workspace
        first_checkbox_label = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.XPATH, "(//label[contains(@class, 'ant-checkbox-wrapper')])[1]"))
        )
        first_checkbox_label.click()

        # Switch back to the main page
        driver.switch_to.default_content()

        time.sleep(3)

        # Drop down 'admin' or 'user'
        # Click the dropdown to open options
        dropdown = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.XPATH, '/html/body/div[4]/div/div[2]/div/div[1]/div/div[2]/div/div[4]/div/div[1]/div[2]/div/div/span/span[2]'))
        )
        dropdown.click()
        time.sleep(1)  # Wait for dropdown to open

        # Select the desired option
        option_to_select = "User"  # Change to "User" if needed

        option_xpath = f"//div[contains(@class, 'ant-select-item-option') and text()='{option_to_select}']"
        selected_option = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.XPATH, option_xpath))
        )
        selected_option.click()
        time.sleep(3)

        # CLick on Add
        driver.find_element(By.XPATH , '/html/body/div[4]/div/div[2]/div/div[1]/div/div[2]/div/div[5]/button[2]').click()
        time.sleep(3)
        print(f"✅ Member/User added successful for {emailid}")
        test_results.append({"Email": emailid, "Status": "Success -  User added"})


        # 2 .Flight Session

        print("Flight Session to download the Invoice and Report")

        driver.find_element(By.XPATH , '//*[@id="root"]/div/div[1]/div/div/div[1]/div[2]/div[3]').click()
        print("NOW Coming to Flight Session")
        time.sleep(4)

        # Wait for the dropdown (SVG icon) to be clickable and click it
        dropdown = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.XPATH, '//*[@id="root"]/div/div[2]/div/div/div/div[1]/div[2]/div[2]/div'))
        )
        dropdown.click()
        time.sleep(1)  # Allow time for dropdown to expand

        workspace_select = "Haldia tech"

        # Locate the search input field and enter workspace name
        search_input = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.XPATH, "//input[@placeholder='Search workspaces']"))  # Adjust this selector if needed
        )
        search_input.clear()  # Clear any existing text
        search_input.send_keys(workspace_select)
        time.sleep(2)  # Wait for the dropdown to populate
        print("code reached here")
        # Click on the correct workspace option in the dropdown
        dropdown_option_xpath = f"//span[@class='ant-dropdown-menu-title-content']//p[contains(text(), '{workspace_select}')]"
        
        selected_option = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.XPATH, dropdown_option_xpath))
        )
        driver.execute_script("arguments[0].click();", selected_option)  # Click via JS if normal click doesn't work
        print("code reached here")
        time.sleep(3)

        # To close it 
        dropdown = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.XPATH, '//*[@id="root"]/div/div[2]/div/div/div/div[1]/div[2]/div[2]/div'))
        )
        dropdown.click()
        time.sleep(2)

        # Invoice Download

        print("Iniitiating Invoice Download")

        invoice = driver.find_element(By.XPATH, '//*[@id="root"]/div/div[2]/div/div/div/div[1]/div[2]/div[1]/div/div[1]/div/div/button[1]/span')
        invoice.click()
        time.sleep(2)

        #Wait for the modal to appear
        modal = WebDriverWait(driver, 10).until(
            EC.visibility_of_element_located((By.CLASS_NAME, "ant-modal-content"))
        )

        # Wait for the Initiate Download button inside the modal
        initiate_button = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.XPATH, "//button[span[text()='Initiate Download']]"))
        )

        # Scroll to the button in case it's not in view
        driver.execute_script("arguments[0].scrollIntoView(true);", initiate_button)

        # Click using JavaScript to avoid overlay issues
        driver.execute_script("arguments[0].click();", initiate_button)

        print("Invoice Downloading  initiated successfully!")
        test_results.append({"Email": email, "Status": "Success -  Invoice Download initiated"})

        # Wait for 3 seconds to observe
        time.sleep(7)

        #  Report Download ###################

        print("Iniitiating Report Download")

        report_name = "Report FCM"

        # Click on the "Download Report" button
        report_button = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.XPATH, "//button[contains(span/text(), 'Download Report')]"))
        )
        driver.execute_script("arguments[0].click();", report_button) 

        # Wait for the pop-up to appear
        time.sleep(2)  # Alternatively, use explicit wait

        # Locate the Report Name input field inside the modal
        report_name_input = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.XPATH, "//input[@placeholder='Report Name']"))
        )
        report_name_input.clear()
        report_name_input.send_keys(report_name)

        time.sleep(2)

        # Wait and Click the "Create" button inside the modal
        create_button = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.XPATH, "//button[span[text()='Create']]"))
        )
        create_button.click()

        print("Report creation initiated successfully!")
        test_results.append({"Email": email, "Status": "Success -  Report Download initiated"})

        time.sleep(7)

        # 3. Upload the invoice number via CSV

        print("Download invoice by uploading the required invoice number")
        
        # CLick on "Download invoice via CSV"
        download = WebDriverWait(driver , 10).until(
            EC.element_to_be_clickable((By.XPATH, "//button[span[text()='Download Invoice Via CSV']]"))
        )
        download.click()
        
        # Wait for the pop-up to appear
        time.sleep(2)  # Alternatively, use explicit waitddd
        
        # Path to your CSV file
        file_path = "/Users/mac/Desktop/partner/Register FCM/INV NUM FCM.csv"  # Replace with the actual file path

        # Locate the file input inside the drag-and-drop container
        file_input = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.XPATH, "//input[@type='file' and @name='file']"))
        )

        # Debugging: Print if file input is found
        print("File input found:", file_input.is_displayed())

        # Send the file path to the input field (upload the file)
        file_input.send_keys(file_path)
        time.sleep(3)  # Wait to see if the file uploads

        # Debugging: Check if upload success message appears
        try:
            upload_success = WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.XPATH, "//p[contains(text(),'Upload successful')]"))  # Adjust based on UI feedback
            )
            print("File uploaded successfully!")
        except:
            print("Upload success message not found.")


        print("Invoice number CSV uploaded")
        test_results.append({"Email": email, "Status": "Success -  Invoice number CSV uploaded"})



    except Exception as e:
        print(f"❌ Error logging in for {email}: {e}")
        test_results.append({"Email": email, "Status": f"Login Failed - {e}"})
        capture_screenshot(email, "error")


def capture_screenshot(email, error_type):
    """Captures and saves screenshots for debugging."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    screenshot_dir = "screenshots"
    os.makedirs(screenshot_dir, exist_ok=True)
    screenshot_path = os.path.join(screenshot_dir, f"{error_type}_{email.replace('@', '_')}_{timestamp}.png")

    driver.save_screenshot(screenshot_path)
    print(f"📸 Screenshot saved: {screenshot_path}")


@pytest.fixture(scope="session", autouse=True)
def save_results():
    """Saves test results to CSV file after all tests are executed."""
    yield  # Wait until all tests are done
    df = pd.DataFrame(test_results)
    df.to_csv("test_results.csv", index=False)
    print("✅ Test results saved to 'test_results.csv'")
