import React, { useState, useEffect, useCallback } from "react";
import { Link } from "react-router-dom";
import "./IndigoScraper.css";
import StatusBadge from "./StatusBadge";
import { API_BASE_URL } from "../config";

const API_ENDPOINTS = {
  START_SCRAPING: `${API_BASE_URL}/indigo/start_scraping`,
  LAST_STATE: `${API_BASE_URL}/indigo/last_state`,
  SETTINGS: `${API_BASE_URL}/indigo/settings`,
};

// Stage configuration for Indigo scraper
const stageConfig = {
  initialization: {
    name: "Session Initialization",
    steps: ["proxy_setup", "session_setup", "environment_check"],
    next: "request",
    required: true,
  },
  request: {
    name: "Invoice Request",
    steps: [
      "prepare_request",
      "get_invoice_ids",
      "validate_invoice_ids",
      "get_auth_token",
    ],
    next: "processing",
    required: true,
  },
  processing: {
    name: "Invoice Processing",
    steps: ["fetch_invoice", "format_html", "save_file"],
    next: null,
    required: true,
  },
};

const IndigoScraper = ({ socket }) => {
  const [lastRunState, setLastRunState] = useState({});
  const [settings, setSettings] = useState({
    auto_run: false,
    interval: 60,
    next_run: null,
  });
  const [formData, setFormData] = useState({ pnr: "", ssrEmail: "" });
  const [stages, setStages] = useState({
    initialization: { status: "not yet started", message: "", timing: "" },
    request: { status: "not yet started", message: "", timing: "" },
    processing: { status: "not yet started", message: "", timing: "" },
  });
  const [status, setStatus] = useState({
    message: "Waiting to start...",
    type: "info",
  });
  const [eventLogs, setEventLogs] = useState([]);
  const [toast, setToast] = useState(null);

  const showToast = useCallback((message, type = "info") => {
    setToast({ message, type });
    setTimeout(() => setToast(null), 3000);
  }, []);

  const updateStatus = useCallback((message, type = "info") => {
    setStatus({ message, type });
  }, []);

  const formatTimestamp = useCallback((timestamp) => {
    if (!timestamp) return "Not scheduled";
    try {
      return new Date(timestamp).toLocaleString();
    } catch (e) {
      console.error("Invalid timestamp:", e);
      return "Invalid date";
    }
  }, []);

  const updateStageStatus = useCallback((stage, status, message, timing) => {
    setStages((prev) => ({
      ...prev,
      [stage]: {
        status,
        message: message || "In progress...",
        timing: timing ? `${timing}s` : "",
      },
    }));
  }, []);

  const addEventLog = useCallback((data) => {
    setEventLogs((prev) => {
      // Create new log entry with consistent structure and proper timestamp
      const timestamp = data.timestamp ? new Date(data.timestamp) : new Date();
      const newLog = {
        id: `${data.stage}-${data.step}-${timestamp.getTime()}`,
        timestamp: timestamp,
        displayTime: timestamp.toLocaleTimeString(),
        timing: data.timing,
        stage: data.stage,
        step: data.step,
        message: data.message,
        type: data.type || data.status || "info",
        // Add sequence info for sorting stages/steps in correct order
        stageOrder:
          {
            initialization: 1,
            validation: 2,
            request: 3,
            processing: 4,
            completion: 5,
          }[data.stage] || 99,
        stepOrder:
          {
            // Initialization steps
            proxy_setup: 1,
            session_setup: 2,
            environment_check: 3,
            // Validation steps
            pnr_validation: 1,
            email_validation: 2,
            session_validation: 3,
            // Request steps
            prepare_request: 1,
            get_invoice_ids: 2,
            validate_invoice_ids: 3,
            get_auth_token: 4,
            // Processing steps
            fetch_invoice: 1,
            format_html: 2,
            save_file: 3,
          }[data.step] || 99,
      };

      // Remove exact duplicates by matching stage, step, and message
      // within a 2 second window
      const duplicateIndex = prev.findIndex(
        (log) =>
          log.stage === newLog.stage &&
          log.step === newLog.step &&
          log.message === newLog.message &&
          Math.abs(log.timestamp - newLog.timestamp) < 2000 // 2 second window
      );

      let nextLogs =
        duplicateIndex >= 0
          ? prev // If duplicate found, don't add
          : [...prev, newLog];

      // Sort logs by:
      // 1. Timestamp
      // 2. Stage order if timestamps are equal
      // 3. Step order if stage is equal
      nextLogs.sort((a, b) => {
        const timeDiff = a.timestamp - b.timestamp;
        if (timeDiff !== 0) return timeDiff;

        const stageDiff = a.stageOrder - b.stageOrder;
        if (stageDiff !== 0) return stageDiff;

        return a.stepOrder - b.stepOrder;
      });

      // Keep most recent 100 logs
      return nextLogs.slice(-100);
    });
  }, []);

  const resetUI = useCallback(() => {
    setStages({
      initialization: { status: "not yet started", message: "", timing: "" },
      request: { status: "not yet started", message: "", timing: "" },
      processing: { status: "not yet started", message: "", timing: "" },
    });
    setStatus({ message: "Initializing scraper...", type: "info" });
    setEventLogs([]);
  }, []);

  const loadInitialState = useCallback(async () => {
    try {
      const response = await fetch(API_ENDPOINTS.LAST_STATE);
      const data = await response.json();
      if (data.success) {
        setLastRunState(data.data || {});
        if (data.data?.pnr) {
          setFormData({
            pnr: data.data.pnr,
            ssrEmail: data.data.ssr_email || "",
          });
        }
      }
    } catch (error) {
      console.error("Error loading initial state:", error);
      showToast("Failed to load initial state", "error");
    }
  }, [showToast]);

  const loadSchedulerSettings = useCallback(async () => {
    try {
      const response = await fetch(API_ENDPOINTS.SETTINGS);
      const data = await response.json();
      if (data.success) {
        setSettings(
          data.data || { auto_run: false, interval: 60, next_run: null }
        );
      }
    } catch (error) {
      console.error("Error loading scheduler settings:", error);
    }
  }, []);

  const handleStartScraper = async (e) => {
    e.preventDefault();
    const form = e.target;

    try {
      if (!form.checkValidity()) {
        throw new Error("Please fill all required fields correctly");
      }

      resetUI();

      const scraperData = {
        "Ticket/PNR": formData.pnr.toUpperCase(),
        SSR_Email: formData.ssrEmail,
        Vendor: "INDIGO AIR",
      };

      const response = await fetch(API_ENDPOINTS.START_SCRAPING, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(scraperData),
      });

      const result = await response.json();
      if (!result.success) {
        throw new Error(result.message);
      }

      updateStatus("Scraper started successfully", "info");
    } catch (error) {
      showToast(error.message, "error");
      updateStatus(error.message, "error");
    }
  };

  const handleSaveSettings = async (e) => {
    e.preventDefault();

    try {
      const newSettings = {
        auto_run: settings.auto_run,
        interval: parseInt(settings.interval),
      };

      if (newSettings.interval < 1 || newSettings.interval > 1440) {
        throw new Error("Interval must be between 1 and 1440 minutes");
      }

      const response = await fetch(API_ENDPOINTS.SETTINGS, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(newSettings),
      });

      const result = await response.json();
      if (!result.success) {
        throw new Error(result.message);
      }

      setSettings(result.data);
      showToast("Settings updated successfully", "success");
    } catch (error) {
      showToast(error.message, "error");
    }
  };

  useEffect(() => {
    const initialize = async () => {
      await Promise.all([loadInitialState(), loadSchedulerSettings()]);
    };
    initialize();
  }, [loadInitialState, loadSchedulerSettings]);

  useEffect(() => {
    // Socket event handlers
    const handlers = {
      indigo_scraper_status: (data) => {
        updateStatus(data.message, data.status === "error" ? "error" : "info");
        if (data.stage && data.status) {
          updateStageStatus(data.stage, data.status, data.message, data.timing);
        }
      },
      indigo_scraper_progress: (data) => {
        if (!data || !data.stage || !data.step) return;

        updateStageStatus(
          data.stage,
          data.status,
          `${data.step}: ${data.message || "In progress..."}`,
          data.data?.timing
        );

        addEventLog(data);
      },
      indigo_scraper_event: (data) => {
        if (!data) return;
        // Only add event log if it's an important event or has a specific type
        if (data.important) {
          addEventLog(data);
        }
      },
      indigo_auto_scrape_complete: (data) => {
        if (data.success) {
          showToast("Auto-scrape completed successfully", "success");
          updateStatus("Auto-scrape completed successfully", "success");
        } else {
          showToast(data.message || "Auto-scrape failed", "error");
          updateStatus(data.message || "Auto-scrape failed", "error");
        }
      },
      indigo_scraper_state_updated: (data) => {
        setLastRunState(data);
      },
      indigo_settings_updated: (data) => {
        setSettings(data);
      },
      indigo_scraper_error: (data) => {
        showToast(data.message, "error");
        updateStatus(data.message, "error");
        if (data.stage) {
          updateStageStatus(data.stage, "error", data.message);
        }
      },
      indigo_scrapper_run_completed: (data) => {
        loadInitialState();
      },
    };

    // Register all socket event handlers
    Object.entries(handlers).forEach(([event, handler]) => {
      socket.on(event, handler);
    });

    // Cleanup function
    return () => {
      Object.keys(handlers).forEach((event) => {
        socket.off(event);
      });
    };
  }, [
    socket,
    updateStatus,
    updateStageStatus,
    addEventLog,
    showToast,
    loadInitialState,
    loadSchedulerSettings,
  ]);

  return (
    <>
      <div className="custom-card-scrapper">
        <div className="content-header">
          <div className="container">
            <div className="d-flex justify-content-between align-items-center">
              <h1 className="content-title">Indigo Air Scraper</h1>
              <Link to="/scrapers" className="btn btn-outline-primary">
                Back to Scrapers
              </Link>
            </div>
          </div>
        </div>

        <div className="container">
          {/* Top Section */}
          <div className="top-section">
            {/* Run Details Card */}
            <div
              className={`card run-details ${
                lastRunState.state === "failed"
                  ? "error"
                  : lastRunState.state === "completed"
                  ? "success"
                  : ""
              }`}
            >
              <div className="card-header">
                <h5 className="mb-0">Run Details</h5>
              </div>
              <div className="card-body">
                <div className="d-flex flex-column gap-2">
                  <p className="mb-2">
                    <strong>Last Run:</strong>{" "}
                    {formatTimestamp(lastRunState.timestamp)}
                  </p>
                  <p className="mb-2">
                    <strong>Status:</strong>{" "}
                    <StatusBadge
                      type={
                        lastRunState.state === "completed"
                          ? "success"
                          : lastRunState.state === "failed"
                          ? "error"
                          : lastRunState.state
                          ? "warning"
                          : "na"
                      }
                      label={lastRunState.state || "Never run"}
                      tooltipText={lastRunState.message}
                    />
                  </p>

                  {lastRunState.state !== "completed" &&
                    lastRunState.state !== "success" && (
                      <p className="mb-2">
                        <strong>Error:</strong>{" "}
                        <span
                          className="error-text"
                          style={{ cursor: "pointer" }}
                          onClick={() =>
                            showToast(lastRunState.message, "error", 0)
                          }
                        >
                          {lastRunState.message
                            ? lastRunState.message.length > 50
                              ? lastRunState.message.substring(0, 50) + "..."
                              : lastRunState.message
                            : "None"}
                        </span>
                      </p>
                    )}

                  <p className="mb-2">
                    <strong>Next Run:</strong>{" "}
                    {formatTimestamp(settings.next_run)}
                  </p>
                  <p className="mb-0">
                    <strong>Auto Run:</strong>{" "}
                    <StatusBadge
                      type={settings.auto_run ? "enabled" : "disabled"}
                      label={settings.auto_run ? "Enabled" : "Disabled"}
                    />
                  </p>
                </div>
              </div>
            </div>

            {/* Scraper Form Card */}
            <div className="card start-scraper-card">
              <div className="card-header">
                <h5 className="mb-0">Start Scraper</h5>
              </div>
              <div className="card-body">
                <form
                  onSubmit={handleStartScraper}
                  className="needs-validation"
                  noValidate
                >
                  <div className="form-content">
                    <div className="mb-3">
                      <label htmlFor="pnr" className="form-label">
                        PNR Number
                      </label>
                      <input
                        type="text"
                        className="form-control"
                        id="pnr"
                        value={formData.pnr}
                        onChange={(e) =>
                          setFormData((prev) => ({
                            ...prev,
                            pnr: e.target.value,
                          }))
                        }
                        pattern="[A-Za-z0-9]{6}"
                        required
                      />
                      <div className="invalid-feedback">
                        Please provide a valid 6-character PNR.
                      </div>
                    </div>
                    <div className="mb-3">
                      <label htmlFor="ssrEmail" className="form-label">
                        SSR Email
                      </label>
                      <input
                        type="email"
                        className="form-control"
                        id="ssrEmail"
                        value={formData.ssrEmail}
                        onChange={(e) =>
                          setFormData((prev) => ({
                            ...prev,
                            ssrEmail: e.target.value,
                          }))
                        }
                        required
                      />
                      <div className="invalid-feedback">
                        Please provide a valid email address.
                      </div>
                    </div>
                  </div>
                  <button type="submit" className="btn btn-primary w-100">
                    Start Scraping
                  </button>
                </form>
              </div>
            </div>

            {/* Scheduler Settings Card */}
            <div className="card">
              <div className="card-header">
                <h5 className="mb-0">Scheduler Settings</h5>
              </div>
              <div className="card-body">
                <form onSubmit={handleSaveSettings}>
                  <div className="mb-3">
                    <div className="form-check form-switch">
                      <input
                        className="form-check-input"
                        type="checkbox"
                        id="autoRunEnabled"
                        checked={settings.auto_run}
                        onChange={(e) =>
                          setSettings((prev) => ({
                            ...prev,
                            auto_run: e.target.checked,
                          }))
                        }
                      />
                      <label
                        className="form-check-label"
                        htmlFor="autoRunEnabled"
                      >
                        Enable Auto Run
                      </label>
                    </div>
                  </div>
                  <div className="mb-3">
                    <label htmlFor="runInterval" className="form-label">
                      Run Interval (minutes)
                    </label>
                    <input
                      type="number"
                      className="form-control"
                      id="runInterval"
                      value={settings.interval}
                      onChange={(e) =>
                        setSettings((prev) => ({
                          ...prev,
                          interval: e.target.value,
                        }))
                      }
                      min="1"
                      max="1440"
                    />
                    <div className="form-text">
                      Interval between 1 and 1440 minutes (24 hours)
                    </div>
                  </div>
                  <div className="mb-3">
                    <label className="form-label">Next Scheduled Run:</label>
                    <p
                      className={`mb-0 ${
                        settings.auto_run ? "text-success" : "text-muted"
                      }`}
                    >
                      {formatTimestamp(settings.next_run)}
                    </p>
                  </div>
                  <button type="submit" className="btn btn-primary w-100">
                    Save Settings
                  </button>
                </form>
              </div>
            </div>
          </div>

          {/* Bottom Section */}
          <div className="bottom-section">
            {/* Scraper Progress Card */}
            <div className="card h-100">
              <div className="card-header">
                <h5 className="mb-0">Scraper Progress</h5>
              </div>
              <div className="card-body">
                <div id="scrapperStatus" className="alert alert-infoo mb-4">
                  <p
                    className={`mb-0 text-${
                      status.type === "info" ? "" : "error"
                    }`}
                  >
                    {status.message}
                  </p>
                </div>

                <div className="stages-container">
                  {Object.entries(stageConfig).map(([stageId, config]) => (
                    <div
                      key={stageId}
                      className={`stage ${
                        stages[stageId].status === "active"
                          ? "active"
                          : stages[stageId].status === "completed"
                          ? "completed"
                          : stages[stageId].status === "error"
                          ? "error"
                          : ""
                      }`}
                    >
                      <div className="stage-content">
                        <h6 className="stage-label mb-2">
                          {config.name} {config.required && "(Required)"}
                        </h6>
                        <p className="mb-1">
                          {stages[stageId].message || "not yet started"}
                        </p>
                        <small className="text-muted">
                          {stages[stageId].timing}
                        </small>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            </div>

            {/* Event Log Card */}
            <div className="card h-100">
              <div className="card-header">
                <h5 className="mb-0">Event Log</h5>
              </div>
              <div className="card-body p-0">
                <div className="event-log">
                  {[...eventLogs].map((log) => (
                    <div key={log.id} className={`event-item ${log.type}`}>
                      <div className="d-flex justify-content-between align-items-start">
                        <strong className="text-muted">
                          {log.displayTime}
                        </strong>
                        {log.timing && (
                          <span className="text-muted">({log.timing}s)</span>
                        )}
                      </div>
                      <div className="mt-1">
                        <strong>
                          {log.stage && `[${log.stage}] `}
                          {log.step && `[${log.step}] `}
                        </strong>
                        {log.message}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Toast Container */}
      {toast && (
        <div className="toast-container position-fixed top-0 end-0 p-3">
          <div
            className={`toast show bg-${
              toast.type === "error" ? "danger" : "success"
            } text-white`}
          >
            <div className="toast-body">
              {toast.message}
              <button
                type="button"
                className="btn-close btn-close-white"
                onClick={() => setToast(null)}
              />
            </div>
          </div>
        </div>
      )}
    </>
  );
};

export default IndigoScraper;
