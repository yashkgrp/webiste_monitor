import React, { useState, useEffect, useCallback } from "react";
import { Link } from "react-router-dom";
import "./IndigoScraper.css";
import StatusBadge from "./StatusBadge";
import Tabs from "./Tabs";
import { API_BASE_URL } from "../config";

const API_ENDPOINTS = {
  START_SCRAPING: `${API_BASE_URL}/run_starair_scraper`,
  LAST_STATE: `${API_BASE_URL}/scraper/last_state`,
  SETTINGS: `${API_BASE_URL}/scraper/settings`,
  CHANGES: `${API_BASE_URL}/scraper/dom_changes`,
};

// Updated stage configuration for Star Air scraper
const stageConfig = {
  initialization: {
    name: "Initialization",
    steps: ["browser_setup", "components_init"],
    next: "login",
    required: true,
  },
  login: {
    name: "Login",
    steps: ["prepare_request", "submit_login"],
    next: "navigation",
    required: true,
  },
  navigation: {
    name: "Navigation",
    steps: ["find_invoices", "extract_links"],
    next: "download",
    required: true,
  },
  download: {
    name: "Download",
    steps: ["process_invoices", "download_files", "verify_files"],

    required: true,
  },
};

const StarAirScraper = ({ socket }) => {
  const [lastRunState, setLastRunState] = useState({});
  const [settings, setSettings] = useState({
    auto_run: false,
    interval: 60,
    next_run: null,
  });
  const [formData, setFormData] = useState({ pnr: "", gstin: "" });
  const [stages, setStages] = useState({
    initialization: { status: "not yet started", message: "", timing: "" },
    login: { status: "not yet started", message: "", timing: "" },
    navigation: { status: "not yet started", message: "", timing: "" },
    download: { status: "not yet started", message: "", timing: "" },
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
    setStages((prev) => {
      const newStages = { ...prev };

      // Update the current stage
      newStages[stage] = {
        status,
        message: message || "In progress...",
        timing: timing ? `${timing}s` : "",
      };

      // If stage completed or succeeded, mark previous stages as completed
      if (status === "completed" || status === "success") {
        const stageOrder = Object.keys(stageConfig);
        const currentIndex = stageOrder.indexOf(stage);

        // Mark all previous stages as completed
        for (let i = 0; i < currentIndex; i++) {
          const prevStage = stageOrder[i];
          if (newStages[prevStage].status !== "completed") {
            newStages[prevStage] = {
              ...newStages[prevStage],
              status: "completed",
            };
          }
        }

        // If current stage completed, mark next stage as active if it exists
        if (currentIndex < stageOrder.length - 1) {
          const nextStage = stageOrder[currentIndex + 1];
          newStages[nextStage] = {
            ...newStages[nextStage],
            status: "active",
          };
        }
      }

      return newStages;
    });
  }, []);

  const normalizeMessage = (message) => {
    // Remove redundant stage prefixes if they exist in square brackets
    const withoutBrackets = message.replace(
      /^\[(initialization|login|navigation|download|completion)\]\s+/i,
      ""
    );

    // Remove the stage name if it starts with it and a colon
    return withoutBrackets.replace(
      /^(Initialization|Login|Navigation|Download|Completion):\s+/i,
      ""
    );
  };

  const normalizeStage = (stage) => {
    // Convert stage names to lowercase and remove square brackets if present
    if (!stage) return "";
    return stage.toLowerCase().replace(/^\[|\]$/g, "");
  };

  const getMessageIdentifier = (message) => {
    // Create a unique identifier for logically equivalent messages
    return message
      .toLowerCase()
      .replace(/\s+/g, " ")
      .replace(/[\d.]+\s*seconds?/, "X seconds")
      .replace(/\d{4}_\d{2}_\d{5}/, "XXXXX")
      .replace(/\\temp.*\.pdf/, "temp/file.pdf");
  };

  const addEventLog = useCallback((data) => {
    setEventLogs((prev) => {
      const timestamp = data.timestamp ? new Date(data.timestamp) : new Date();
      const normalizedStage = normalizeStage(data.stage);
      const normalizedMessage = normalizeMessage(data.message);
      const messageIdentifier = getMessageIdentifier(normalizedMessage);

      const newLog = {
        id: `${normalizedStage}-${timestamp.getTime()}-${messageIdentifier}`,
        timestamp,
        displayTime: timestamp.toLocaleTimeString(),
        timing: data.timing,
        stage: normalizedStage,
        message: normalizedMessage,
        type: data.status || "info",
      };

      // Add new log and ensure proper ordering
      return (
        [newLog, ...prev]
          // Remove duplicates based on messageIdentifier within a 2-second window
          .filter((log, index, self) => {
            // Keep only the first occurrence of a message within 2 seconds
            const isDuplicate =
              self.findIndex(
                (t) =>
                  getMessageIdentifier(t.message) ===
                    getMessageIdentifier(log.message) &&
                  Math.abs(t.timestamp - log.timestamp) < 2000
              ) === index;
            return isDuplicate;
          })
          // Sort by timestamp in descending order (newest first)
          .sort((a, b) => b.timestamp - a.timestamp)
          .slice(0, 100)
      ); // Keep only last 100 logs
    });
  }, []);

  const resetUI = useCallback(() => {
    setStages({
      initialization: { status: "not yet started", message: "", timing: "" },
      login: { status: "not yet started", message: "", timing: "" },
      navigation: { status: "not yet started", message: "", timing: "" },
      download: { status: "not yet started", message: "", timing: "" },
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
            gstin: data.data.gstin || "",
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
          data.settings || { auto_run: false, interval: 60, next_run: null }
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
        setDomChanges(data.data || []);
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

      const scraperState = {
        pnr: formData.pnr.toUpperCase(),
        gstin: formData.gstin,
      };

      const formDat = new FormData();
      formDat.append("pnr", formData.pnr.toUpperCase());
      formDat.append("gstin", formData.gstin);
      formDat.append("frontend_state", JSON.stringify(scraperState));

      const response = await fetch(API_ENDPOINTS.START_SCRAPING, {
        method: "POST",
        body: formDat,
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

      setSettings(result.settings);
      showToast("Settings updated successfully", "success");
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
      scraper_status: (data) => {
        // Handle different status types
        if (data.status === "debug") {
          addEventLog(data);
        } else {
          updateStatus(
            data.message,
            data.status === "error" ? "error" : "info"
          );
          if (data.stage) {
            updateStageStatus(
              data.stage,
              data.status,
              data.message,
              data.timing
            );
          }
        }
      },
      scraper_progress: (data) => {
        if (!data) return;
        const stage = data.stage?.toLowerCase();
        if (stage) {
          updateStageStatus(
            stage,
            data.status || "active",
            data.message,
            data.timing
          );
          addEventLog(data);
        }
      },
      scraper_event: (data) => {
        if (!data) return;
        addEventLog(data);
      },
      scraper_auto_run_complete: (data) => {
        if (data.success) {
          showToast("Auto-scrape completed successfully", "success");
          updateStatus("Auto-scrape completed successfully", "success");
          // Mark all stages as completed
          Object.keys(stageConfig).forEach((stage) => {
            updateStageStatus(stage, "completed");
          });
        } else {
          showToast(data.message || "Auto-scrape failed", "error");
          updateStatus(data.message || "Auto-scrape failed", "error");
        }
      },
      scraper_state_updated: (data) => {
        setLastRunState(data);
      },
      settings_updated: (data) => {
        setSettings(data);
      },
      scraper_error: (data) => {
        showToast(data.message, "error");
        updateStatus(data.message, "error");
        if (data.stage) {
          updateStageStatus(data.stage, "error", data.message);
        }
      },
      scraper_run_completed: () => {
        // Mark all stages as completed when scraper finishes
        Object.keys(stageConfig).forEach((stage) => {
          updateStageStatus(stage, "completed");
        });
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
                    lastRunState.state === "success"
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
                      {lastRunState.error
                        ? lastRunState.error.length > 50
                          ? lastRunState.error.substring(0, 50) + "..."
                          : lastRunState.error
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
                  <label htmlFor="gstin" className="form-label">
                    GSTIN
                  </label>
                  <input
                    type="text"
                    className="form-control"
                    id="gstin"
                    value={formData.gstin}
                    onChange={(e) =>
                      setFormData((prev) => ({
                        ...prev,
                        gstin: e.target.value,
                      }))
                    }
                    pattern="[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[1-9A-Z]{1}[Z]{1}[0-9A-Z]{1}"
                    required
                  />
                  <div className="invalid-feedback">
                    Please provide a valid GSTIN.
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
                  <th>GSTIN</th>
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
                    <td>{change.pnr || "N/A"}</td>
                    <td>{change.gstin || "N/A"}</td>
                    <td>{change.changes?.length || 0} change(s)</td>
                    <td>{change.page_id || "N/A"}</td>
                    <td>
                      <span
                        className={`badge ${
                          change.type === "structural_change"
                            ? "bg-warning"
                            : "bg-success"
                        }`}
                      >
                        {change.type === "structural_change"
                          ? "Structure Changed"
                          : "Content Changed"}
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
                  <strong>Page:</strong> {selectedChange.page_id || "Unknown"}
                  <br />
                  <strong>PNR:</strong> {selectedChange.pnr || "N/A"}
                  <br />
                  <strong>GSTIN:</strong> {selectedChange.gstin || "N/A"}
                </div>
                <div className="changes-list">
                  {selectedChange.changes.map((change, idx) => (
                    <div key={idx} className="card mb-2">
                      <div
                        className={`card-header ${
                          change.type === "removed"
                            ? "bg-danger text-white"
                            : change.type === "added"
                            ? "bg-success text-white"
                            : "bg-warning"
                        }`}
                      >
                        {change.type.charAt(0).toUpperCase() +
                          change.type.slice(1)}
                      </div>
                      <div className="card-body">
                        <p>
                          <strong>Element Type:</strong>{" "}
                          {change.attributes?.tag || "Unknown"}
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
                        {change.description && (
                          <p className="mb-0 mt-2">
                            <strong>Description:</strong>
                            <br />
                            {change.description}
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

  return (
    <>
      <div className="custom-card-scrapper">
        <div className="content-header">
          <div className="container">
            <div className="d-flex justify-content-between align-items-center">
              <h1 className="content-title">Star Air Scraper</h1>
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

export default StarAirScraper;
