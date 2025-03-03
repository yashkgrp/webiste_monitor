import React, { useState, useEffect, useCallback } from "react";
import { API_BASE_URL } from "../config";
import Analytics from "./Analytics";
import StatusBadge from "./StatusBadge";

const API_ENDPOINTS = {
  URL_LIST: `${API_BASE_URL}/sync`,
  ADD_URL: `${API_BASE_URL}/add_url`,
  DELETE_URL: `${API_BASE_URL}/delete_url`,
  URL_STATUS: `${API_BASE_URL}/toggle_pause`,
  URL_ANALYTICS: `${API_BASE_URL}/url/analytics`,
};

const URLMonitor = ({ socket }) => {
  const [urls, setUrls] = useState([]);
  const [newUrl, setNewUrl] = useState("");
  const [interval, setInterval] = useState("5");
  const [error, setError] = useState("");
  const [showAnalytics, setShowAnalytics] = useState(false);
  const [selectedUrl, setSelectedUrl] = useState(null);
  const [loadingActions, setLoadingActions] = useState({});

  useEffect(() => {
    loadInitialData();

    // Socket event listeners
    socket.on("update_data", updateDisplay);
    socket.on("url_added", handleUrlAdded);
    socket.on("url_deleted", handleUrlDeleted);
    socket.on("url_paused", handleUrlPaused);

    return () => {
      socket.off("update_data");
      socket.off("url_added");
      socket.off("url_deleted");
      socket.off("url_paused");
    };
  }, [socket]);

  const loadInitialData = async () => {
    try {
      const response = await fetch(API_ENDPOINTS.URL_LIST);
      const result = await response.json();

      if (result.status === "success") {
        updateDisplay(result.data);
      } else {
        setError("Failed to load initial data");
      }
    } catch (error) {
      console.error("Error loading initial data:", error);
      setError("Failed to connect to server");
    }
  };

  const updateDisplay = (data) => {
    if (!Array.isArray(data)) {
      console.error("Invalid data format:", data);
      return;
    }
    setUrls(data);
  };

  const handleUrlAdded = (data) => {
    showSuccess(data.message || "URL added successfully");
    loadInitialData();
  };

  const handleUrlDeleted = () => {
    showSuccess("URL deleted successfully");
    loadInitialData();
  };

  const handleUrlPaused = () => {
    loadInitialData();
  };

  const addUrl = async (event) => {
    event.preventDefault();
    try {
      const response = await fetch(API_ENDPOINTS.ADD_URL, {
        method: "POST",
        headers: {
          "Content-Type": "application/x-www-form-urlencoded",
        },
        credentials: "include",
        body: `new_url=${encodeURIComponent(
          newUrl
        )}&interval=${encodeURIComponent(interval)}`,
      });

      const data = await response.json();

      setNewUrl("");
      setInterval("5");
      setError("");
      showSuccess(data.message || "URL added successfully");
    } catch (error) {
      console.error("Error adding URL:", error);
      setError(error.message);
    }
  };

  const togglePause = async (url) => {
    try {
      setLoadingActions((prev) => ({ ...prev, [url]: true }));
      const response = await fetch(API_ENDPOINTS.URL_STATUS, {
        method: "POST",
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
        credentials: "include",
        body: `url=${encodeURIComponent(url)}`,
      });
    } catch (error) {
      console.error("Error toggling pause:", error);
    } finally {
      setLoadingActions((prev) => ({ ...prev, [url]: false }));
    }
  };

  const deleteUrl = async (url) => {
    if (window.confirm("Are you sure you want to delete this URL?")) {
      try {
        const response = await fetch(API_ENDPOINTS.DELETE_URL, {
          method: "POST",
          headers: { "Content-Type": "application/x-www-form-urlencoded" },
          credentials: "include",
          body: `url=${encodeURIComponent(url)}`,
        });
      } catch (error) {
        console.error("Error deleting URL:", error);
        setError("Failed to delete URL");
      }
    }
  };

  const showSuccess = (message) => {
    setError(message);
    setTimeout(() => setError(""), 3000);
  };

  const openAnalytics = (url) => {
    setSelectedUrl(url);
    setShowAnalytics(true);
  };

  return (
    <>
      {error && (
        <div
          className={`alert ${
            error.includes("success") ? "alert-success" : "alert-danger"
          }`}
        >
          {error}
        </div>
      )}

      <div className="custom-card">
        <div className="content-header">
          <h1 className="content-title">URL Monitor</h1>
        </div>

        <div className="url-form">
          <form onSubmit={addUrl}>
            <input
              type="url"
              className="form-control"
              id="newUrl"
              value={newUrl}
              onChange={(e) => setNewUrl(e.target.value)}
              placeholder="Enter URL to monitor"
              required
            />
            <input
              type="number"
              className="form-control"
              id="interval"
              value={interval}
              onChange={(e) => setInterval(e.target.value)}
              placeholder="Check interval (seconds)"
              required
            />
            <button type="submit" className="btn btn-primary">
              <svg
                xmlns="http://www.w3.org/2000/svg"
                width="24"
                height="24"
                viewBox="0 0 25 24"
                fill="none"
              >
                <path
                  d="M12.25 5V19M5.25 12H19.25"
                  stroke="white"
                  strokeWidth="1.5"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
              </svg>
              Add URL
            </button>
          </form>
        </div>

        <div className="table-container">
          <div className="table-responsive">
            <table className="table">
              <thead>
                <tr>
                  <th>URL</th>
                  <th>Status</th>
                  <th>Response Time</th>
                  <th>Avg Response Time</th>
                  <th>Interval</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {urls.map((site, index) => (
                  <tr key={index}>
                    <td>
                      <a
                        href="#"
                        onClick={(e) => {
                          e.preventDefault();
                          openAnalytics(site.url);
                        }}
                        className="text-decoration-none"
                      >
                        {site.url}
                      </a>
                    </td>
                    <td>
                      <StatusBadge
                        type={
                          site.status.startsWith("Down:")
                            ? "down"
                            : site.status === "Slow"
                            ? "slow"
                            : "up"
                        }
                        label={
                          site.status.startsWith("Down:") ? "Down" : site.status
                        }
                        tooltipText={
                          site.status.startsWith("Down:")
                            ? site.status.substring(6)
                            : undefined
                        }
                      />
                    </td>
                    <td>{site.last_response_time.toFixed(2)} ms</td>
                    <td>{site.avg_response_time.toFixed(2)} ms</td>
                    <td>{site.interval} seconds</td>
                    <td>
                      <div className="action-icons">
                        <button
                          onClick={() => togglePause(site.url)}
                          className="btn btn-icon me-2"
                          title={site.paused ? "Resume" : "Pause"}
                          disabled={loadingActions[site.url]}
                        >
                          {loadingActions[site.url] ? (
                            <span className="spinner-border spinner-border-sm" />
                          ) : (
                            <i
                              className={`bi bi-${
                                site.paused ? "play" : "pause"
                              }`}
                            />
                          )}
                        </button>
                        <button
                          onClick={() => openAnalytics(site.url)}
                          className="btn btn-icon me-2"
                          title="Analytics"
                        >
                          <i className="bi bi-graph-up"></i>
                        </button>
                        <button
                          onClick={() => deleteUrl(site.url)}
                          className="btn btn-icon text-danger delete-action"
                          title="Delete"
                        >
                          <i className="bi bi-trash"></i>
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>

      <Analytics
        url={selectedUrl}
        show={showAnalytics}
        onHide={() => setShowAnalytics(false)}
      />
    </>
  );
};

export default URLMonitor;
