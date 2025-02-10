import os
import time
import shutil
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import json
import chromedriver_autoinstaller
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager

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

def rename_downloaded_file(downloaded_file, pnr, row_number, download_folder):
    """
    Renames the downloaded file to include the PNR number and row number.
    Ensures the first file is named with _1 to avoid overwriting.
    """
    new_file_name = f"{pnr}_{row_number}.pdf"  # Always append _row_number
    new_file_path = os.path.join(download_folder, new_file_name)

    shutil.move(downloaded_file, new_file_path)  # Move and rename the file
    print(f"Renamed file: {new_file_path}")
    
    return new_file_path  # Return the correct renamed file path

def wait_for_download(download_folder, previous_files, timeout=30):
    """
    Waits for a new file to appear in the download folder that wasn't there before.
    Ensures the download is complete before returning the file path.
    """
    end_time = time.time() + timeout
    while time.time() < end_time:
        current_files = set(os.listdir(download_folder))
        new_files = current_files - previous_files  # Detect new files
        for file in new_files:
            file_path = os.path.join(download_folder, file)
            if file.endswith(".pdf") and os.path.getsize(file_path) > 0:
                print(f"Downloaded new file: {file_path}")
                return file_path  # Return the newly downloaded file
        time.sleep(1)
    return None

def save_files_locally(files, base_path="downloaded_tickets"):
    """Save files to local directory instead of S3"""
    os.makedirs(base_path, exist_ok=True)
    saved_paths = []
    
    for file in files:
        filename = os.path.basename(file)
        destination = os.path.join(base_path, filename)
        shutil.copy2(file, destination)
        print(f"Saved file locally: {destination}")
        saved_paths.append(destination)
    
    return saved_paths

def airasia_scraper(data, PORT):
    """
    Modified scraper function that saves files locally instead of S3
    """
    try:
        vendor = data['Vendor']
        airline = 'airasia' if vendor != 'Air India Express' else 'airindiaexpress'
        pnr = data['Ticket/PNR']
        code = data['Origin']
        
        # Setup download folder
        download_folder = os.path.join(os.getcwd(), "downloads")
        os.makedirs(download_folder, exist_ok=True)
        print(f"Download folder created at: {download_folder}")
        
        driver = setup_chrome_options(download_folder)
        if not driver:
            return {"success": False, "message": "WebDriver initialization failed", "data": {}}
        
        print("Navigating to Air India Express website...")
        driver.get("https://www.airindiaexpress.com/gst-tax-invoice")
        time.sleep(3)

        # Fill form
        pnr_input = driver.find_element(By.XPATH, '//*[@id="pnr"]')
        pnr_input.send_keys(pnr)
        
        origin_input = driver.find_element(By.XPATH, '//*[@id="Origin"]')
        origin_input.send_keys(code)
        time.sleep(2)
        
        try:
            suggestion_option = WebDriverWait(driver, 10).until(
                EC.element_to_be_clickable((By.XPATH, "//div[@class='Source_List_Gst'][1]"))
            )
            suggestion_option.click()
            time.sleep(5)
        except Exception as e:
            # Save the page source for debugging
            error_html_path = os.path.join(download_folder, f"error_page_{pnr}.html")
            with open(error_html_path, "w", encoding="utf-8") as f:
                f.write(driver.page_source)
            print(f"Saved error page HTML to: {error_html_path}")
            print(f"Error selecting suggestion: {str(e)}")
            driver.quit()
            return {"success": False, "message": "PORTAL ISSUE", "data": {}}
        
        try:
            search_button = driver.find_element(By.CLASS_NAME, "search-button")
            search_button.click()
            time.sleep(5)
        except Exception as e:
            print(f"Error clicking search button: {str(e)}")
            driver.quit()
            return {"success": False, "message": "PORTAL ISSUE", "data": {}}

        # Get total rows
        rows = driver.find_elements(By.XPATH, '//*[@id="spa-root"]/div/div[170]/div[1]/div/div[1]/div[2]/div[1]/div/div[1]/div[5]/table/tbody/tr')
        row_count = len(rows)
        
        if row_count == 0:
            driver.quit()
            return {"success": False, "message": "INVALID DATA", "data": {}}
        
        print(f"Total rows found: {row_count}")
        
        downloaded_files = []
        previous_files = set(os.listdir(download_folder))
        
        for i in range(1, row_count + 1):
            try:
                print(f"Processing row {i}...")
                download_button = driver.find_element(By.XPATH, f'//*[@id="spa-root"]/div/div[170]/div[1]/div/div[1]/div[2]/div[1]/div/div[1]/div[5]/table/tbody/tr[{i}]/td[1]/img')
                download_button.click()
                time.sleep(2)
                
                downloaded_file = wait_for_download(download_folder, previous_files)
                if downloaded_file:
                    renamed_file = rename_downloaded_file(downloaded_file, pnr, i, download_folder)
                    print(f"Successfully downloaded and renamed file: {renamed_file}")
                    downloaded_files.append(renamed_file)
                    previous_files.add(os.path.basename(renamed_file))
            except Exception as e:
                print(f"Error processing row {i}: {str(e)}")
        
        local_paths = save_files_locally(downloaded_files)
        driver.quit()
        print("Scraping completed successfully")
        
        return {
            "success": True,
            "message": "Files saved locally",
            "data": {'local_paths': local_paths, 'airline': airline}
        }
    
    except Exception as e:
        print(f"Error during scraping: {str(e)}")
        if 'driver' in locals():
            driver.quit()
        return {
            "success": False,
            "message": str(e),
            "data": {}
        }

if __name__ == "__main__":
    # Test data for debugging
    test_data = {
        'Ticket/PNR': 'C7ZGRA',
        'Origin': 'BLR',
        'Vendor': 'Air Asia'
    }
    
    print("Starting debug run...")
    print("Test data:", test_data)
    
    # Run the scraper
    result = airasia_scraper(test_data, PORT=None)
    
    print("\nScraping Results:")
    print("Success:", result["success"])
    print("Message:", result["message"])
    print("Data:", json.dumps(result["data"], indent=2))

