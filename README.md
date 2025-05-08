# Website Monitoring and Scraping Automation Project

## 1. Overview

This project is designed to monitor website availability, track DOM changes, and automate web scraping tasks for various airline and portal websites. It features a Flask-based web server with SocketIO for real-time updates, background schedulers for automated tasks, and a notification system via email and Slack. Firestore is used as the backend database.

## 2. Core Components

### 2.1. Main Server (`server.py`)

*   **Flask Application**: Serves as the backbone of the project, handling HTTP requests, rendering templates (though front-end is separate), and managing SocketIO connections.
*   **SocketIO Integration**: Enables real-time communication between the server and clients, used for updating website statuses, scraper progress, and DOM changes.
*   **Schedulers (APScheduler)**: Manages automated tasks, including:
    *   Periodic URL monitoring.
    *   Scheduled scraper runs for different airlines/portals.
    *   Each scraper (Star Air, Akasa, Air India Express, Portal) has its own scheduler initialization logic (e.g., `initialize_scheduler`, `initialize_akasa_scheduler`, `initialize_airindia_scheduler`, `initialize_portal_scheduler` in [`server.py`](c%3A%5CUsers%5Cyash%20chawla%5CDesktop%5Cfinkraft%5Cwebiste_monitor-beta%20-%20Copy%20(8)%5Cwebiste_monitor-beta%5Cserver.py)).
*   **Firebase Initialization**: Connects to Firebase Firestore and Storage at startup using credentials from environment variables (via `initialize_firebase` from `config.py`).
*   **Centralized Logging**: Implements logging for server operations, errors, and debug information.

### 2.2. URL Monitoring (`monitor_urls` function in `server.py`)

*   **Purpose**: Continuously checks the status and response time of a list of monitored URLs.
*   **Process**:
    1.  Loads URLs to monitor from Firestore (`db_ops.sync_urls()`).
    2.  Periodically (based on configured interval for each URL), sends an HTTP GET request to each URL.
    3.  Uses default headers to mimic a browser. Specific headers (e.g., `Referer`, `Origin`) are added for certain domains like `goindigo.in`.
    4.  Calculates response time.
    5.  Determines status ("Up", "Slow", "Down" with error code/message).
    6.  Calculates a rolling average of response times for the last 5 checks to determine "Slow" status.
    7.  Updates the URL status, response time, and last check time in Firestore (`db_ops.update_url_status()`).
    8.  Emits `update_data` via SocketIO to refresh client UIs.
    9.  Sends notifications (email and Slack via `NotificationHandler`) if a significant status change occurs (e.g., from "Up" to "Down", or "Down" to "Up"). A 5-second cooldown is implemented between notifications for the same URL.
*   **Configuration**: URLs, check intervals, and pause status are managed via API endpoints (`/add_url`, `/delete_url`, `/toggle_pause`) and stored in Firestore.

### 2.3. Notification System

*   **`NotificationHandler` (`notification_handler.py`)**: Central class for dispatching various types of notifications.
    *   Uses [`SlackNotifier`](c%3A%5CUsers%5Cyash%20chawla%5CDesktop%5Cfinkraft%5Cwebiste_monitor-beta%20-%20Copy%20(8)%5Cwebiste_monitor-beta%5Cslack_utils.py) for Slack messages and functions from [`email_utils.py`](c%3A%5CUsers%5Cyash%20chawla%5CDesktop%5Cfinkraft%5Cwebiste_monitor-beta%20-%20Copy%20(8)%5Cwebiste_monitor-beta%5Cemail_utils.py) for emails.
    *   Methods:
        *   `send_website_status_notification()`: For website up/down/recovery alerts.
        *   `send_scraper_notification()`: For scraper errors.
        *   `send_dom_change_notification()`: For DOM change alerts.
*   **`SlackNotifier` (`slack_utils.py`)**:
    *   Initializes with `SLACK_BOT_TOKEN` and `SLACK_CHANNEL_ID` from environment variables.
    *   Provides methods to send formatted messages for scraper errors, DOM changes, website down alerts, and website recovery alerts.
*   **`email_utils.py`**:
    *   `send_email()`: Core function to send emails using SMTP (configured via environment variables like `SMTP_SERVER`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`).
    *   `generate_status_email()`: Creates HTML email body for website status.
    *   `generate_scraper_error_email()`: Creates HTML email body for scraper errors, including PNR, GSTIN/Traveller Name, stage, and error message. It can also include the `scraper_name`.
    *   `generate_dom_change_email()`: Creates HTML email body for DOM changes, detailing the path, element, and description of changes.
    *   `send_notification_email()`: Sends an email to a list of notification recipients.
*   **Logging**:
    *   [`email_logger.py`](c%3A%5CUsers%5Cyash%20chawla%5CDesktop%5Cfinkraft%5Cwebiste_monitor-beta%20-%20Copy%20(8)%5Cwebiste_monitor-beta%5Cemail_logger.py): Logs successful email sends and errors to `logs/email_logs.log`.
    *   `smtp_logger.py`: Logs SMTP connection attempts, TLS, login, and errors.

### 2.4. DOM Change Tracking (`dom_utils.py`)

*   **`DOMChangeTracker` Class**:
    *   **Purpose**: Detects and stores significant structural changes in the HTML DOM of web pages.
    *   **`clean_html()`**: Preprocesses HTML by removing scripts, styles, meta tags, and irrelevant attributes to focus on structural elements.
    *   **`compare_dom()`**: Compares cleaned old and new HTML content using `difflib.Differ`. Identifies added or removed structural tags (div, form, input, button, nav).
    *   **`store_dom_changes()`**:
        1.  Retrieves the previous DOM snapshot for a `page_id` from Firestore.
        2.  Compares it with the new `html_content`.
        3.  If significant changes are found, stores the new snapshot and a record of the changes (including `page_id`, `timestamp`, `gstin`, `pnr`, `changes` list, `type`, content sizes) in Firestore.
        4.  Used by scrapers (e.g., Star Air scraper in [`scraper_utils.py`](c%3A%5CUsers%5Cyash%20chawla%5CDesktop%5Cfinkraft%5Cwebiste_monitor-beta%20-%20Copy%20(8)%5Cwebiste_monitor-beta%5Cscraper_utils.py)) to monitor page structure.
    *   **`store_dom_changes_akasa()`**: A specialized version for Akasa, comparing structure after removing dynamic content and attributes.
    *   **`get_recent_changes()`**: Retrieves a list of recent DOM change records from Firestore.
    *   **`track_page_changes()`**: A method likely used by Air India scraper for tracking changes.
*   **Notifications**: When DOM changes are detected by a scraper, `NotificationHandler.send_dom_change_notification()` is called to alert via email and Slack.

### 2.5. Database Operations

*   **`db_operations.py` (`FirestoreDB` class)**: Handles general Firestore interactions for URL monitoring and the Star Air scraper.
    *   Manages URLs: `sync_urls`, `add_url`, `delete_url`, `update_url_status`, `get_url_data`, `get_url_history`.
    *   Manages scraper state: `store_scraper_state`, `get_last_scraper_state`, `get_all_scraper_states`.
    *   Manages scheduler settings: `get_scheduler_settings`, `update_scheduler_settings`.
    *   Manages DOM data: `get_dom_snapshot`, `store_dom_data`, `get_dom_changes`, `get_last_dom_comparison_result`.
    *   Analytics: `analyze_best_times`, `get_hourly_averages`, `get_reliability_stats`, `get_scraper_analytics`.
*   **Scraper-Specific DB Ops**:
    *   [`akasa_scrappper/akasa_db_ops.py`](c%3A%5CUsers%5Cyash%20chawla%5CDesktop%5Cfinkraft%5Cwebiste_monitor-beta%20-%20Copy%20(8)%5Cwebiste_monitor-beta%5Cakasa_scrappper%5Cakasa_db_ops.py) (`AkasaFirestoreDB`): Tailored for Akasa scraper's state, settings, and DOM changes.
    *   [`air_scrapper/db_ops.py`](c%3A%5CUsers%5Cyash%20chawla%5CDesktop%5Cfinkraft%5Cwebiste_monitor-beta%20-%20Copy%20(8)%5Cwebiste_monitor-beta%5Cair_scrapper%5Cdb_ops.py) (`AirIndiaFirestoreDB`): For Air India Express scraper's state, settings, and DOM changes.
    *   [`portal_base/db_util.py`](c%3A%5CUsers%5Cyash%20chawla%5CDesktop%5Cfinkraft%5Cwebiste_monitor-beta%20-%20Copy%20(8)%5Cwebiste_monitor-beta%5Cportal_base%5Cdb_util.py) (`PortalFirestoreDB`): For generic portal scrapers.

### 2.6. Socket Logging (`socket_logger.py`)

*   **`SocketLogger` Class**: Provides methods to log scraper stages, status, and errors, potentially for real-time display or debugging through SocketIO events, though the primary emission is handled directly in scraper utility functions.

## 3. Scraper Architecture and Types

The project employs primarily **API-based scraping** using the `requests` library. While "Selenium-based" was mentioned, the provided core scraper logic (e.g., [`scraper_utils.py`](c%3A%5CUsers%5Cyash%20chawla%5CDesktop%5Cfinkraft%5Cwebiste_monitor-beta%20-%20Copy%20(8)%5Cwebiste_monitor-beta%5Cscraper_utils.py)) does not use Selenium. If Selenium is used, it would be in other, non-provided scraper modules.

Scrapers generally follow one of two architectural patterns for their backend logic:

### 3.1. Monolithic (Logic primarily in `server.py`)

*   Some older or simpler scraper integrations might have their route handlers, core logic, and state management directly within [`server.py`](c%3A%5CUsers%5Cyash%20chawla%5CDesktop%5Cfinkraft%5Cwebiste_monitor-beta%20-%20Copy%20(8)%5Cwebiste_monitor-beta%5Cserver.py).
*   Example: The initial Star Air scraper logic (`run_starair_scraper` route, `fetch_invoices`, `startair_scraper` functions) appears to have evolved, with parts now in [`scraper_utils.py`](c%3A%5CUsers%5Cyash%20chawla%5CDesktop%5Cfinkraft%5Cwebiste_monitor-beta%20-%20Copy%20(8)%5Cwebiste_monitor-beta%5Cscraper_utils.py).

### 3.2. Modular (Separated Files)

*   More recent or complex scrapers adopt a modular structure, typically involving:
    1.  **Core Scraper Logic File**: Contains the main scraping functions, interaction with the target website, data extraction, and SocketIO status emissions.
        *   Examples: [`scraper_utils.py`](c%3A%5CUsers%5Cyash%20chawla%5CDesktop%5Cfinkraft%5Cwebiste_monitor-beta%20-%20Copy%20(8)%5Cwebiste_monitor-beta%5Cscraper_utils.py) (for Star Air), [`akasa_scrappper/akasascrapper_util.py`](c%3A%5CUsers%5Cyash%20chawla%5CDesktop%5Cfinkraft%5Cwebiste_monitor-beta%20-%20Copy%20(8)%5Cwebiste_monitor-beta%5Cakasa_scrappper%5Cakasascrapper_util.py), [`air_scrapper/air_scraper.py`](c%3A%5CUsers%5Cyash%20chawla%5CDesktop%5Cfinkraft%5Cwebiste_monitor-beta%20-%20Copy%20(8)%5Cwebiste_monitor-beta%5Cair_scrapper%5Cair_scraper.py).
    2.  **Database Management File**: A dedicated class for managing scraper-specific data in Firestore (state, settings, DOM changes, history).
        *   Examples: [`db_operations.py`](c%3A%5CUsers%5Cyash%20chawla%5CDesktop%5Cfinkraft%5Cwebiste_monitor-beta%20-%20Copy%20(8)%5Cwebiste_monitor-beta%5Cdb_operations.py), [`akasa_scrappper/akasa_db_ops.py`](c%3A%5CUsers%5Cyash%20chawla%5CDesktop%5Cfinkraft%5Cwebiste_monitor-beta%20-%20Copy%20(8)%5Cwebiste_monitor-beta%5Cakasa_scrappper%5Cakasa_db_ops.py), [`air_scrapper/db_ops.py`](c%3A%5CUsers%5Cyash%20chawla%5CDesktop%5Cfinkraft%5Cwebiste_monitor-beta%20-%20Copy%20(8)%5Cwebiste_monitor-beta%5Cair_scrapper%5Cdb_ops.py).
    3.  **Routes File**: Defines Flask routes specific to that scraper, typically for initiating scrapes, fetching state/settings, and viewing DOM changes. These are often initialized and registered with the main Flask app in [`server.py`](c%3A%5CUsers%5Cyash%20chawla%5CDesktop%5Cfinkraft%5Cwebiste_monitor-beta%20-%20Copy%20(8)%5Cwebiste_monitor-beta%5Cserver.py).
        *   Examples: [`fcm/server_routes.py`](c%3A%5CUsers%5Cyash%20chawla%5CDesktop%5Cfinkraft%5Cwebiste_monitor-beta%20-%20Copy%20(8)%5Cwebiste_monitor-beta%5Cfcm%5Cserver_routes.py), [`alliance_copy/server_routes.py`](c%3A%5CUsers%5Cyash%20chawla%5CDesktop%5Cfinkraft%5Cwebiste_monitor-beta%20-%20Copy%20(8)%5Cwebiste_monitor-beta%5Calliance_copy%5Cserver_routes.py), [`indigo/server_routes.py`](c%3A%5CUsers%5Cyash%20chawla%5CDesktop%5Cfinkraft%5Cwebiste_monitor-beta%20-%20Copy%20(8)%5Cwebiste_monitor-beta%5Cindigo%5Cserver_routes.py), [`portal_base/server_routes.py`](c%3A%5CUsers%5Cyash%20chawla%5CDesktop%5Cfinkraft%5Cwebiste_monitor-beta%20-%20Copy%20(8)%5Cwebiste_monitor-beta%5Cportal_base%5Cserver_routes.py).

## 4. Module-Specific Documentation

### 4.1. Star Air Scraper

*   **Core Logic**: [`scraper_utils.py`](c%3A%5CUsers%5Cyash%20chawla%5CDesktop%5Cfinkraft%5Cwebiste_monitor-beta%20-%20Copy%20(8)%5Cwebiste_monitor-beta%5Cscraper_utils.py) (`StarAirScraper` class, `run_scraper` function).
    *   Uses `requests` library for HTTP interactions.
    *   **Workflow**:
        1.  `login()`: Accesses login page, extracts `__RequestVerificationToken`, submits login form with PNR and GSTIN. Checks for DOM changes on the login page using `DOMChangeTracker`.
        2.  `find_invoice_links()`: Parses the response to find "Print" links for invoices.
        3.  `download_invoices()` & `process_single_invoice()`:
            *   Iterates through invoice links.
            *   Fetches each invoice HTML page.
            *   Converts HTML to PDF using `pdfkit` (requires `wkhtmltopdf` installed and configured via `WKHTMLTOPDF_PATH`). The PDF is saved temporarily and then deleted. *Note: The current implementation in `scraper_utils.py` deletes the PDF locally; S3 upload logic might be elsewhere or intended.*
            *   Emits detailed status updates via SocketIO at each step (`emit_status`).
*   **DB Operations**: Uses the generic `FirestoreDB` from [`db_operations.py`](c%3A%5CUsers%5Cyash%20chawla%5CDesktop%5Cfinkraft%5Cwebiste_monitor-beta%20-%20Copy%20(8)%5Cwebiste_monitor-beta%5Cdb_operations.py).
*   **Routes**: Primarily in [`server.py`](c%3A%5CUsers%5Cyash%20chawla%5CDesktop%5Cfinkraft%5Cwebiste_monitor-beta%20-%20Copy%20(8)%5Cwebiste_monitor-beta%5Cserver.py) (e.g., `/run_starair_scraper`, `/scraper/last_state`, `/scraper/dom_changes`, `/scraper/settings`).
*   **Scheduling**: `initialize_scheduler()` and `run_automated_scrape()` in [`server.py`](c%3A%5CUsers%5Cyash%20chawla%5CDesktop%5Cfinkraft%5Cwebiste_monitor-beta%20-%20Copy%20(8)%5Cwebiste_monitor-beta%5Cserver.py).

### 4.2. Akasa Air Scraper

*   **Directory**: `akasa_scrappper/`
*   **Core Logic**: [`akasascrapper_util.py`](c%3A%5CUsers%5Cyash%20chawla%5CDesktop%5Cfinkraft%5Cwebiste_monitor-beta%20-%20Copy%20(8)%5Cwebiste_monitor-beta%5Cakasa_scrappper%5Cakasascrapper_util.py) (contains `run_scraper` for Akasa).
*   **DB Operations**: [`akasa_db_ops.py`](c%3A%5CUsers%5Cyash%20chawla%5CDesktop%5Cfinkraft%5Cwebiste_monitor-beta%20-%20Copy%20(8)%5Cwebiste_monitor-beta%5Cakasa_scrappper%5Cakasa_db_ops.py) (`AkasaFirestoreDB`).
*   **Routes**: In [`server.py`](c%3A%5CUsers%5Cyash%20chawla%5CDesktop%5Cfinkraft%5Cwebiste_monitor-beta%20-%20Copy%20(8)%5Cwebiste_monitor-beta%5Cserver.py) (e.g., `/akasa/start_scraping`, `/akasa/last_state`, `/akasa/dom_changes`, `/akasa/settings`).
*   **Scheduling**: `initialize_akasa_scheduler()` and `run_akasa_automated_scrape()` in [`server.py`](c%3A%5CUsers%5Cyash%20chawla%5CDesktop%5Cfinkraft%5Cwebiste_monitor-beta%20-%20Copy%20(8)%5Cwebiste_monitor-beta%5Cserver.py).
*   **DOM Tracking**: Uses `DOMChangeTracker.store_dom_changes_akasa()`.

### 4.3. Air India Express Scraper

*   **Directory**: `air_scrapper/`
*   **Core Logic**: [`air_scraper.py`](c%3A%5CUsers%5Cyash%20chawla%5CDesktop%5Cfinkraft%5Cwebiste_monitor-beta%20-%20Copy%20(8)%5Cwebiste_monitor-beta%5Cair_scrapper%5Cair_scraper.py) (contains `run_scraper` for Air India Express).
    *   Also includes `air_scraper copy.py` and `air_scrappper_raw.py` which might be variants or development versions.
*   **DB Operations**: [`db_ops.py`](c%3A%5CUsers%5Cyash%20chawla%5CDesktop%5Cfinkraft%5Cwebiste_monitor-beta%20-%20Copy%20(8)%5Cwebiste_monitor-beta%5Cair_scrapper%5Cdb_ops.py) (`AirIndiaFirestoreDB`).
*   **Routes**: In [`server.py`](c%3A%5CUsers%5Cyash%20chawla%5CDesktop%5Cfinkraft%5Cwebiste_monitor-beta%20-%20Copy%20(8)%5Cwebiste_monitor-beta%5Cserver.py) (e.g., `/air_india/start_scraping`, `/air_india/last_state`, `/air_india/dom_changes`, `/air_india/settings`).
*   **Scheduling**: `initialize_airindia_scheduler()` and `run_airindia_automated_scrape()` in [`server.py`](c%3A%5CUsers%5Cyash%20chawla%5CDesktop%5Cfinkraft%5Cwebiste_monitor-beta%20-%20Copy%20(8)%5Cwebiste_monitor-beta%5Cserver.py).
*   **DOM Utilities**: Uses [`dom_util.py`](c%3A%5CUsers%5Cyash%20chawla%5CDesktop%5Cfinkraft%5Cwebiste_monitor-beta%20-%20Copy%20(8)%5Cwebiste_monitor-beta%5Cair_scrapper%5Cdom_util.py) (potentially a custom DOM utility or an older version).

### 4.4. Alliance Air Scraper

*   **Directory**: `alliance_copy/`
*   **Core Logic**: [`alliance_scrapper.py`](c%3A%5CUsers%5Cyash%20chawla%5CDesktop%5Cfinkraft%5Cwebiste_monitor-beta%20-%20Copy%20(8)%5Cwebiste_monitor-beta%5Calliance_copy%5Calliance_scrapper.py).
    *   `alliance_raw.py` might be a raw data processing or initial scraping script.
*   **Routes**: [`server_routes.py`](c%3A%5CUsers%5Cyash%20chawla%5CDesktop%5Cfinkraft%5Cwebiste_monitor-beta%20-%20Copy%20(8)%5Cwebiste_monitor-beta%5Calliance_copy%5Cserver_routes.py), initialized in [`server.py`](c%3A%5CUsers%5Cyash%20chawla%5CDesktop%5Cfinkraft%5Cwebiste_monitor-beta%20-%20Copy%20(8)%5Cwebiste_monitor-beta%5Cserver.py) via `init_alliance_routes`.
*   **Logging**: `alliance_scraper.log` suggests file-based logging for this scraper.

### 4.5. Indigo Scraper

*   **Directory**: `indigo/`
*   **Core Logic**: `indigo_scraper.py` (expected, based on `indigo_scraper.log` and `indigo_raw.py`).
    *   `indigo_raw.py` likely for initial data fetching/processing.
*   **DB Operations**: [`db_util.py`](c%3A%5CUsers%5Cyash%20chawla%5CDesktop%5Cfinkraft%5Cwebiste_monitor-beta%20-%20Copy%20(8)%5Cwebiste_monitor-beta%5Cindigo%5Cdb_util.py).
*   **DOM Utilities**: [`dom_util.py`](c%3A%5CUsers%5Cyash%20chawla%5CDesktop%5Cfinkraft%5Cwebiste_monitor-beta%20-%20Copy%20(8)%5Cwebiste_monitor-beta%5Cindigo%5Cdom_util.py).
*   **Routes**: [`server_routes.py`](c%3A%5CUsers%5Cyash%20chawla%5CDesktop%5Cfinkraft%5Cwebiste_monitor-beta%20-%20Copy%20(8)%5Cwebiste_monitor-beta%5Cindigo%5Cserver_routes.py), initialized in [`server.py`](c%3A%5CUsers%5Cyash%20chawla%5CDesktop%5Cfinkraft%5Cwebiste_monitor-beta%20-%20Copy%20(8)%5Cwebiste_monitor-beta%5Cserver.py) via `init_indigo_routes`.
*   **Logging**: `indigo_scraper.log`.

### 4.6. Spicejet Scraper

*   **Directory**: `spicejet/`
*   **Core Logic**: [`spicejet.py`](c%3A%5CUsers%5Cyash%20chawla%5CDesktop%5Cfinkraft%5Cwebiste_monitor-beta%20-%20Copy%20(8)%5Cwebiste_monitor-beta%5Cspicejet%5Cspicejet.py).
    *   `spicejet_raw.py` for raw data handling.
*   **DB Operations**: [`db_util.py`](c%3A%5CUsers%5Cyash%20chawla%5CDesktop%5Cfinkraft%5Cwebiste_monitor-beta%20-%20Copy%20(8)%5Cwebiste_monitor-beta%5Cspicejet%5Cdb_util.py).
*   **DOM Utilities**: [`dom_util.py`](c%3A%5CUsers%5Cyash%20chawla%5CDesktop%5Cfinkraft%5Cwebiste_monitor-beta%20-%20Copy%20(8)%5Cwebiste_monitor-beta%5Cspicejet%5Cdom_util.py).
*   **Routes**: [`server_routes.py`](c%3A%5CUsers%5Cyash%20chawla%5CDesktop%5Cfinkraft%5Cwebiste_monitor-beta%20-%20Copy%20(8)%5Cwebiste_monitor-beta%5Cspicejet%5Cserver_routes.py) (expected, though not explicitly initialized in the provided `server.py` snippet, it's a common pattern).

### 4.7. FCM (Firebase Cloud Messaging) / Generic Portal Scraper

*   **Directory**: `fcm/` and `portal_base/`
*   **Purpose**: The `fcm` directory seems related to a specific portal or functionality, possibly Firebase Cloud Messaging for push notifications, or a portal named "FCM". The `portal_base` directory provides a generic structure for portal scrapers.
*   **FCM Files**:
    *   [`fcm.py`](c%3A%5CUsers%5Cyash%20chawla%5CDesktop%5Cfinkraft%5Cwebiste_monitor-beta%20-%20Copy%20(8)%5Cwebiste_monitor-beta%5Cfcm%5Cfcm.py): Core logic for the FCM portal/feature.
    *   [`db_util.py`](c%3A%5CUsers%5Cyash%20chawla%5CDesktop%5Cfinkraft%5Cwebiste_monitor-beta%20-%20Copy%20(8)%5Cwebiste_monitor-beta%5Cfcm%5Cdb_util.py): Database operations.
    *   [`server_routes.py`](c%3A%5CUsers%5Cyash%20chawla%5CDesktop%5Cfinkraft%5Cwebiste_monitor-beta%20-%20Copy%20(8)%5Cwebiste_monitor-beta%5Cfcm%5Cserver_routes.py): Routes, initialized via `init_fcm_routes` in [`server.py`](c%3A%5CUsers%5Cyash%20chawla%5CDesktop%5Cfinkraft%5Cwebiste_monitor-beta%20-%20Copy%20(8)%5Cwebiste_monitor-beta%5Cserver.py).
    *   `file_handler.py`: Utility for file operations.
    *   `.fernet_key`: Suggests encryption/decryption capabilities.
*   **Portal Base Files (`portal_base/`)**:
    *   [`db_util.py`](c%3A%5CUsers%5Cyash%20chawla%5CDesktop%5Cfinkraft%5Cwebiste_monitor-beta%20-%20Copy%20(8)%5Cwebiste_monitor-beta%5Cportal_base%5Cdb_util.py) (`PortalFirestoreDB`): Generic DB utility for portals.
    *   [`server_routes.py`](c%3A%5CUsers%5Cyash%20chawla%5CDesktop%5Cfinkraft%5Cwebiste_monitor-beta%20-%20Copy%20(8)%5Cwebiste_monitor-beta%5Cportal_base%5Cserver_routes.py): Generic routes, initialized via `init_portal_routes`.
    *   `initialize_portal_scheduler`: Function in [`server.py`](c%3A%5CUsers%5Cyash%20chawla%5CDesktop%5Cfinkraft%5Cwebiste_monitor-beta%20-%20Copy%20(8)%5Cwebiste_monitor-beta%5Cserver.py) to set up scheduled tasks for portals using `PortalFirestoreDB`.

## 5. Configuration

*   **Environment Variables**: The application relies heavily on environment variables for configuration:
    *   Firebase credentials (implicitly, via `initialize_firebase`).
    *   Slack: `SLACK_BOT_TOKEN`, `SLACK_CHANNEL_ID`.
    *   Email: `SMTP_SERVER`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_NOTIFICATIONEMAIL`.
    *   `WKHTMLTOPDF_PATH` (in [`scraper_utils.py`](c%3A%5CUsers%5Cyash%20chawla%5CDesktop%5Cfinkraft%5Cwebiste_monitor-beta%20-%20Copy%20(8)%5Cwebiste_monitor-beta%5Cscraper_utils.py)) for PDF generation.
*   **Firebase Console**: Firestore database rules, indexes, and potentially other Firebase service configurations.

## 6. Running the Application

1.  Ensure all Python dependencies are installed (e.g., Flask, Flask-SocketIO, requests, beautifulsoup4, pdfkit, google-cloud-firestore, apscheduler, slack_sdk).
2.  Install `wkhtmltopdf` and ensure `WKHTMLTOPDF_PATH` in [`scraper_utils.py`](c%3A%5CUsers%5Cyash%20chawla%5CDesktop%5Cfinkraft%5Cwebiste_monitor-beta%20-%20Copy%20(8)%5Cwebiste_monitor-beta%5Cscraper_utils.py) points to the executable.
3.  Set up all required environment variables.
4.  Run `python server.py`.

The server will start, initialize Firebase, schedulers, and begin monitoring URLs and running scheduled scraping tasks.

## 7. Logging

*   **General Application Logging**: Configured in [`server.py`](c%3A%5CUsers%5Cyash%20chawla%5CDesktop%5Cfinkraft%5Cwebiste_monitor-beta%20-%20Copy%20(8)%5Cwebiste_monitor-beta%5Cserver.py) using the `logging` module. Outputs to console and potentially files if handlers are added.
*   **Email Logging**: [`email_logger.py`](c%3A%5CUsers%5Cyash%20chawla%5CDesktop%5Cfinkraft%5Cwebiste_monitor-beta%20-%20Copy%20(8)%5Cwebiste_monitor-beta%5Cemail_logger.py) logs email sending activity to `logs/email_logs.log`.
*   **SMTP Logging**: `smtp_logger.py` logs SMTP interactions.
*   **Scraper-Specific Logs**: Some scrapers (e.g., Alliance, Indigo) have their own `.log` files (e.g., `alliance_scraper.log`).
*   **SocketIO Logging**: `SocketLogger` in [`socket_logger.py`](c%3A%5CUsers%5Cyash%20chawla%5CDesktop%5Cfinkraft%5Cwebiste_monitor-beta%20-%20Copy%20(8)%5Cwebiste_monitor-beta%5Csocket_logger.py) and direct `socketio.emit` calls provide real-time status updates.

---
This documentation provides a detailed overview of the project structure, core components, and individual scraper modules based on the provided file structure and code snippets.
