import React, { useState, useEffect, useCallback } from "react";
import { Link } from "react-router-dom";
import "./IndigoScraper.css";
import StatusBadge from "./StatusBadge";
import { API_BASE_URL } from "../config";

const API_ENDPOINTS = {
  START_SCRAPING: `${API_BASE_URL}/akasa/start_scraping`,
  LAST_STATE: `${API_BASE_URL}/akasa/last_state`,
  SETTINGS: `${API_BASE_URL}/akasa/settings`,
};

// Stage configuration for Akasa scraper
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

const AkasaScraper = ({ socket }) => {
  const [lastRunState, setLastRunState] = useState({});
  const [settings, setSettings] = useState({
    auto_run: false,
    interval: 60,
    next_run: null,
  });
  const [formData, setFormData] = useState({ pnr: "", travellerName: "" });
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

  // Update stage status callback to handle previous stages
  const updateStageStatus = useCallback((stage, status, message, timing) => {
    setStages((prev) => {
      // Get ordered list of stages
      const orderedStages = ["initialization", "request", "processing"];
      const currentIndex = orderedStages.indexOf(stage);

      // Create new state object
      const newStages = { ...prev };

      // Mark all previous stages as completed when current stage is active or later
      if (currentIndex > 0) {
        for (let i = 0; i < currentIndex; i++) {
          const prevStage = orderedStages[i];
          newStages[prevStage] = {
            ...newStages[prevStage],
            status: "completed",
            message: newStages[prevStage].message || "Completed",
          };
        }
      }

      // Update current stage
      newStages[stage] = {
        status,
        message: message || "In progress...",
        timing: timing ? `${timing}s` : "",
      };

      return newStages;
    });
  }, []);

  const addEventLog = useCallback((data) => {
    setEventLogs((prev) => {
      const timestamp = new Date();
      const newLog = {
        id: `${data.stage}-${data.step}-${timestamp.getTime()}`,
        timestamp: timestamp,
        displayTime: timestamp.toLocaleTimeString(),
        timing: data.timing,
        stage: data.stage,
        step: data.step,
        message: data.message,
        type: data.type || data.status || "info",
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
            proxy_setup: 1,
            session_setup: 2,
            environment_check: 3,
            prepare_request: 1,
            get_invoice_ids: 2,
            validate_invoice_ids: 3,
            get_auth_token: 4,
            fetch_invoice: 1,
            format_html: 2,
            save_file: 3,
          }[data.step] || 99,
      };

      const duplicateIndex = prev.findIndex(
        (log) =>
          log.stage === newLog.stage &&
          log.step === newLog.step &&
          log.message === newLog.message &&
          Math.abs(log.timestamp - newLog.timestamp) < 2000
      );

      let nextLogs = duplicateIndex >= 0 ? prev : [...prev, newLog];

      nextLogs.sort((a, b) => {
        const timeDiff = a.timestamp - b.timestamp;
        if (timeDiff !== 0) return timeDiff;
        const stageDiff = a.stageOrder - b.stageOrder;
        if (stageDiff !== 0) return stageDiff;
        return a.stepOrder - b.stepOrder;
      });

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
        // Update lastRunState with all fields from data.data
        setLastRunState(data.data || {});
        if (data.data?.pnr) {
          setFormData({
            pnr: data.data.pnr,
            travellerName: data.data.traveller_name || "",
          });
        }
        // Also update settings since some settings info comes in last_state
        setSettings((prev) => ({
          ...prev,
          auto_run: data.data.auto_run,
          next_run: data.data.next_run,
        }));
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
      if (data.success && data.settings) {
        setSettings((prev) => ({
          ...prev,
          auto_run: data.settings.auto_run,
          interval: data.settings.interval,
          next_run: data.settings.next_run,
        }));
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
        pnr: formData.pnr.toUpperCase(),
        traveller_name: formData.travellerName,
        vendor: "AKASA AIR",
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

      // Update settings with response data
      setSettings({
        auto_run: result.auto_run,
        interval: result.interval,
        next_run: result.next_run,
      });

      // Refresh initial state to update UI with latest data
      await loadInitialState();
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

  // Update socket event handlers
  useEffect(() => {
    // Socket event handlers for Akasa
    const handlers = {
      akasa_scraper_status: (data) => {
        updateStatus(data.message, data.status === "error" ? "error" : "info");
        if (data.stage && data.status) {
          // Add slight delay for visual feedback as in HTML version
          setTimeout(() => {
            updateStageStatus(
              data.stage,
              data.status,
              data.message,
              data.timing
            );
          }, 300);
        }
      },
      akasa_scraper_progress: (data) => {
        if (!data || !data.stage || !data.step) return;

        updateStageStatus(
          data.stage,
          data.status,
          `${data.step}: ${data.message || "In progress..."}`,
          data.data?.timing
        );

        addEventLog(data);
      },
      akasa_scraper_event: (data) => {
        if (!data) return;

        addEventLog(data);
      },
      akasa_auto_scrape_complete: (data) => {
        if (data.success) {
          showToast("Auto-scrape completed successfully", "success");
          updateStatus("Auto-scrape completed successfully", "success");
        } else {
          showToast(data.message || "Auto-scrape failed", "error");
          updateStatus(data.message || "Auto-scrape failed", "error");
        }
      },
      akasa_scraper_state_updated: (data) => {
        setLastRunState(data);
      },
      akasa_settings_updated: (data) => {
        setSettings(data);
      },
      akasa_scraper_error: (data) => {
        showToast(data.message, "error");
        updateStatus(data.message, "error");
        if (data.stage) {
          updateStageStatus(data.stage, "error", data.message);
        }
      },
      akasa_scraper_completed: (data) => {
        loadInitialState();
      },
    };

    Object.entries(handlers).forEach(([event, handler]) => {
      socket.on(event, handler);
    });

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
  ]);

  // Update bottom section JSX to handle stage status classes more precisely
  return (
    <>
      <div className="custom-card-scrapper">
        <div className="content-header">
          <div className="container">
            <div className="d-flex justify-content-between align-items-center">
              <h1 className="content-title">Akasa Air Scraper</h1>
              <Link to="/scrapers" className="btn btn-outline-primary">
                Back to Scrapers
              </Link>
            </div>
          </div>
        </div>

        <div className="container">
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
                    {formatTimestamp(lastRunState.last_run)}
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

            {/* Start Scraper Form */}
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
                      <label htmlFor="travellerName" className="form-label">
                        Traveller Name
                      </label>
                      <input
                        type="text"
                        className="form-control"
                        id="travellerName"
                        value={formData.travellerName}
                        onChange={(e) =>
                          setFormData((prev) => ({
                            ...prev,
                            travellerName: e.target.value,
                          }))
                        }
                        required
                      />
                      <div className="invalid-feedback">
                        Please provide the traveller name.
                      </div>
                    </div>
                  </div>
                  <button type="submit" className="btn btn-primary w-100">
                    Start Scraping
                  </button>
                </form>
              </div>
            </div>

            {/* Scheduler Settings */}
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

          <div className="bottom-section">
            {/* Scraper Progress */}
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
                  {Object.entries(stageConfig).map(([stageId, config]) => {
                    const stageStatus = stages[stageId].status;
                    const stageClass =
                      stageStatus === "active"
                        ? "active"
                        : stageStatus === "completed"
                        ? "completed"
                        : stageStatus === "error"
                        ? "error"
                        : "";

                    return (
                      <div
                        key={stageId}
                        className={`stage ${stageClass}`}
                        style={{
                          backgroundColor:
                            stageClass === "active"
                              ? "#fff3cd"
                              : stageClass === "completed"
                              ? "#d4edda"
                              : stageClass === "error"
                              ? "#f8d7da"
                              : "",
                          borderColor:
                            stageClass === "active"
                              ? "#ffeeba"
                              : stageClass === "completed"
                              ? "#c3e6cb"
                              : stageClass === "error"
                              ? "#f5c6cb"
                              : "",
                        }}
                      >
                        <div className="stage-content">
                          <h6 className="stage-label mb-2">
                            {config.name} {config.required && "(Required)"}
                          </h6>
                          <p
                            className={`mb-1 ${
                              stageStatus === "error" ? "text-danger" : ""
                            }`}
                          >
                            {stages[stageId].message || "not yet started"}
                          </p>
                          <small className="text-muted">
                            {stages[stageId].timing}
                          </small>
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>
            </div>

            {/* Event Log */}
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

export default AkasaScraper;
