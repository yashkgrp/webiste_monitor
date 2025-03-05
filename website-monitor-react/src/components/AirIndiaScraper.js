import React, { useState, useEffect, useCallback } from "react";
import { Link } from "react-router-dom";
import "./IndigoScraper.css";
import StatusBadge from "./StatusBadge";
import Tabs from "./Tabs";
import { API_BASE_URL } from "../config";

const API_ENDPOINTS = {
  START_SCRAPING: `${API_BASE_URL}/air_india/start_scraping`,
  LAST_STATE: `${API_BASE_URL}/air_india/last_state`,
  SETTINGS: `${API_BASE_URL}/air_india/settings`,
  CHANGES: `${API_BASE_URL}/air_india/dom_changes`,
};

// Stage configuration for Air India scraper
const stageConfig = {
  initialization: {
    name: "Session Initialization",
    steps: ["browser_setup"],
    next: "request",
    required: true,
  },
  request: {
    name: "Invoice Request",
    steps: ["page_load", "form_fill", "captcha_solving", "submission"],
    next: "processing",
    required: true,
  },
  processing: {
    name: "Invoice Processing",
    steps: ["download", "verify_files", "save_files"],
    next: null,
    required: true,
  },
};

const AirIndiaScraper = ({ socket }) => {
  const [lastRunState, setLastRunState] = useState({});
  const [settings, setSettings] = useState({
    auto_run: false,
    interval: 60,
    next_run: null,
  });
  const [formData, setFormData] = useState({ pnr: "", origin: "", vendor: "" });
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
  const [activeTab, setActiveTab] = useState("scraper");
  const [domChanges, setDomChanges] = useState([]);
  const [isLoadingChanges, setIsLoadingChanges] = useState(false);
  const [selectedChange, setSelectedChange] = useState(null);
  const [showChangeModal, setShowChangeModal] = useState(false);

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
    if (data.stage === "info") {
      return;
    }
    setEventLogs((prev) => {
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
      };

      const nextLogs = [newLog, ...prev].slice(0, 100);
      return nextLogs;
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
            origin: data.data.origin || "",
            vendor: data.data.vendor || "",
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
          data.settings || {
            auto_run: false,
            interval: 60,
            next_run: null,
          }
        );
      }
    } catch (error) {
      console.error("Error loading scheduler settings:", error);
    }
  }, []);

  const loadDOMChanges = useCallback(async () => {
    try {
      setIsLoadingChanges(true);
      const response = await fetch(API_ENDPOINTS.CHANGES);
      const data = await response.json();
      if (data.success) {
        setDomChanges(data.data.changes || []);
      }
    } catch (error) {
      console.error("Error loading DOM changes:", error);
      showToast("Failed to load DOM changes", "error");
    } finally {
      setIsLoadingChanges(false);
    }
  }, [showToast]);

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
        origin: formData.origin.toUpperCase(),
        vendor: formData.vendor || "AIR INDIA",
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
        throw new Error(result.message || "Failed to save settings");
      }

      // Update settings directly from result since the settings are in the root object
      setSettings((prev) => ({
        ...prev,
        auto_run: result.auto_run,
        interval: result.interval,
        next_run: result.next_run,
      }));

      showToast(result.message || "Settings updated successfully", "success");
    } catch (error) {
      showToast(error.message, "error");
    }
  };

  useEffect(() => {
    const initialize = async () => {
      await Promise.all([loadInitialState(), loadSchedulerSettings()]);
      await loadDOMChanges();
    };
    initialize();

    // Set up periodic refresh for DOM changes
    const refreshInterval = setInterval(loadDOMChanges, 30000);
    return () => clearInterval(refreshInterval);
  }, [loadInitialState, loadSchedulerSettings, loadDOMChanges]);

  useEffect(() => {
    const handlers = {
      air_scraper_status: (data) => {
        updateStatus(data.message, data.status === "error" ? "error" : "info");
        if (data.stage && data.status) {
          updateStageStatus(data.stage, data.status, data.message, data.timing);
        }
      },
      air_scraper_progress: (data) => {
        if (!data || !data.stage || !data.step) return;

        updateStageStatus(
          data.stage,
          data.status,
          `${data.step}: ${data.message || "In progress..."}`,
          data.data?.timing
        );

        addEventLog(data);
      },
      air_scraper_event: (data) => {
        if (!data) return;
        addEventLog({
          ...data,
          stage: data.stage || "info",
          step: data.step || "system",
          message: data.message,
          type: data.type || "info",
        });
      },
      air_scraper_state_updated: (data) => {
        setLastRunState(data);
      },
      air_scraper_settings_updated: (data) => {
        setSettings(data);
      },
      air_scraper_error: (data) => {
        showToast(data.message, "error");
        updateStatus(data.message, "error");
        if (data.stage) {
          updateStageStatus(data.stage, "error", data.message);
        }
      },
      air_scraper_completed: () => {
        loadInitialState();
        loadDOMChanges();
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
    loadDOMChanges,
  ]);

  const renderScraperContent = () => (
    <>
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
                    <span className="error-text">
                      {lastRunState.message
                        ? lastRunState.message.length > 50
                          ? lastRunState.message.substring(0, 50) + "..."
                          : lastRunState.message
                        : "None"}
                    </span>
                  </p>
                )}

              <p className="mb-2">
                <strong>Next Run:</strong> {formatTimestamp(settings.next_run)}
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
                  <label htmlFor="origin" className="form-label">
                    Origin
                  </label>
                  <input
                    type="text"
                    className="form-control"
                    id="origin"
                    value={formData.origin}
                    onChange={(e) =>
                      setFormData((prev) => ({
                        ...prev,
                        origin: e.target.value,
                      }))
                    }
                    pattern="[A-Za-z]{3}"
                    required
                  />
                  <div className="invalid-feedback">
                    Please provide a valid 3-letter origin code.
                  </div>
                </div>
                <div className="mb-3">
                  <label htmlFor="vendor" className="form-label">
                    Vendor
                  </label>
                  <input
                    type="text"
                    className="form-control"
                    id="vendor"
                    value={formData.vendor}
                    onChange={(e) =>
                      setFormData((prev) => ({
                        ...prev,
                        vendor: e.target.value,
                      }))
                    }
                    placeholder="AIR INDIA"
                  />
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
                  <label className="form-check-label" htmlFor="autoRunEnabled">
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
                    settings?.auto_run ? "text-success" : "text-muted"
                  }`}
                >
                  {formatTimestamp(settings?.next_run)}
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
        {/* Scraper Progress Card */}
        <div className="card h-100">
          <div className="card-header">
            <h5 className="mb-0">Scraper Progress</h5>
          </div>
          <div className="card-body">
            <div id="scrapperStatus" className="alert alert-infoo mb-4">
              <p
                className={`mb-0 text-${status.type === "info" ? "" : "error"}`}
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
              {eventLogs.map((log) => (
                <div key={log.id} className={`event-item ${log.type}`}>
                  <div className="d-flex justify-content-between align-items-start">
                    <strong className="text-muted">{log.displayTime}</strong>
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
    </>
  );

  const renderDOMChangesContent = () => (
    <div className="card">
      <div className="card-header">
        <h5 className="mb-0">DOM Changes History</h5>
      </div>
      <div className="card-body">
        {isLoadingChanges ? (
          <div className="text-center">Loading...</div>
        ) : domChanges.length === 0 ? (
          <div className="text-center text-muted">
            No DOM changes detected yet
          </div>
        ) : (
          <div className="table-responsive">
            <table className="table">
              <thead>
                <tr>
                  <th>Timestamp</th>
                  <th>PNR</th>
                  <th>Origin</th>
                  <th>Changes</th>
                  <th>Page</th>
                  <th>Status</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {domChanges.map((change, index) => (
                  <tr key={change.timestamp}>
                    <td>{new Date(change.timestamp).toLocaleString()}</td>
                    <td>{change.metadata?.pnr || "N/A"}</td>
                    <td>{change.metadata?.origin || "N/A"}</td>
                    <td>{change.changes?.length || 0} change(s)</td>
                    <td>{change.page_id || "N/A"}</td>
                    <td>
                      <span
                        className={`badge ${
                          change.metadata?.has_changes
                            ? "bg-warning"
                            : "bg-success"
                        }`}
                      >
                        {change.metadata?.has_changes
                          ? "Changes Detected"
                          : "No Changes"}
                      </span>
                    </td>
                    <td>
                      {change.changes?.length > 0 && (
                        <button
                          className="btn btn-icon"
                          title="View Changes"
                          onClick={() => {
                            setSelectedChange(change);
                            setShowChangeModal(true);
                          }}
                        >
                          <i
                            className="bi bi-eye"
                            style={{ color: "var(--teal-primary)" }}
                          ></i>
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Changes Modal */}
      {selectedChange && (
        <div
          className={`modal fade ${showChangeModal ? "show" : ""}`}
          style={{ display: showChangeModal ? "block" : "none" }}
          tabIndex="-1"
          role="dialog"
          aria-hidden={!showChangeModal}
        >
          <div className="modal-dialog modal-lg">
            <div className="modal-content">
              <div className="modal-header">
                <h5 className="modal-title">DOM Changes Details</h5>
                <button
                  type="button"
                  className="btn-close"
                  onClick={() => {
                    setShowChangeModal(false);
                    setSelectedChange(null);
                  }}
                />
              </div>
              <div className="modal-body">
                <div className="mb-3">
                  <strong>Timestamp:</strong>{" "}
                  {new Date(selectedChange.timestamp).toLocaleString()}
                  <br />
                  <strong>Page:</strong>{" "}
                  {selectedChange.metadata?.page_id || "Unknown"}
                  <br />
                  <strong>PNR:</strong> {selectedChange.metadata?.pnr || "N/A"}
                  <br />
                  <strong>Origin:</strong>{" "}
                  {selectedChange.metadata?.origin || "N/A"}
                </div>
                <div className="changes-list">
                  {selectedChange.changes.map((change, idx) => (
                    <div key={idx} className="card mb-2">
                      <div
                        className={`card-header ${getChangeHeaderClass(
                          change.type
                        )}`}
                      >
                        {change.type.charAt(0).toUpperCase() +
                          change.type.slice(1)}
                        {change.description && `: ${change.description}`}
                      </div>
                      <div className="card-body">
                        <p>
                          <strong>Element Type:</strong>{" "}
                          {change.element_type || "Unknown"}
                        </p>
                        {change.element && (
                          <div className="mb-3">
                            <strong>Element Content:</strong>
                            <pre className="bg-light p-2 rounded mt-1">
                              <code>{change.element}</code>
                            </pre>
                          </div>
                        )}
                        {change.path && (
                          <p className="mb-0">
                            <strong>DOM Path:</strong>
                            <code className="d-block bg-light p-2 rounded mt-1">
                              {change.path}
                            </code>
                          </p>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
              <div className="modal-footer">
                <button
                  type="button"
                  className="btn btn-secondary"
                  onClick={() => {
                    setShowChangeModal(false);
                    setSelectedChange(null);
                  }}
                >
                  Close
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
      {showChangeModal && (
        <div
          className="modal-backdrop fade show"
          onClick={() => {
            setShowChangeModal(false);
            setSelectedChange(null);
          }}
        ></div>
      )}
    </div>
  );

  const getChangeHeaderClass = (type) => {
    switch (type.toLowerCase()) {
      case "addition":
        return "bg-success text-white";
      case "removal":
        return "bg-danger text-white";
      case "content_change":
        return "bg-warning";
      case "structure_change":
        return "bg-info text-white";
      default:
        return "bg-secondary text-white";
    }
  };

  return (
    <>
      <div className="custom-card-scrapper">
        <div className="content-header">
          <div className="container">
            <div className="d-flex justify-content-between align-items-center">
              <h1 className="content-title">Air India Scraper</h1>
              <Link to="/scrapers" className="btn btn-outline-primary">
                Back to Scrapers
              </Link>
            </div>
          </div>
        </div>

        <div className="container">
          <Tabs
            tabs={[
              { id: "scraper", label: "Scraper" },
              { id: "domChanges", label: "DOM Changes" },
            ]}
            activeTab={activeTab}
            onTabChange={setActiveTab}
          />

          {activeTab === "scraper"
            ? renderScraperContent()
            : renderDOMChangesContent()}
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

export default AirIndiaScraper;
