import React, { useState, useEffect, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import StatusBadge from "./StatusBadge";
import { API_BASE_URL } from "../config";

const API_ENDPOINTS = {
  STAR_AIR: {
    LAST_STATE: `${API_BASE_URL}/scraper/last_state`,
    CHANGES: `${API_BASE_URL}/scraper/dom_changes`,
  },
  AKASA: {
    LAST_STATE: `${API_BASE_URL}/akasa/last_state`,
  },
  AIR_INDIA: {
    LAST_STATE: `${API_BASE_URL}/air_india/last_state`,
  },
  ALLIANCE: {
    LAST_STATE: `${API_BASE_URL}/alliance/last_state`,
    CHANGES: `${API_BASE_URL}/alliance/changes`,
  },
  INDIGO: {
    LAST_STATE: `${API_BASE_URL}/indigo/last_state`,
  },
};

const Scrapers = ({ socket }) => {
  const navigate = useNavigate();
  const [scraperStates, setScraperStates] = useState({
    starAir: {},
    akasa: {},
    airIndia: {},
    alliance: {},
    indigo: {},
  });

  const [domChanges, setDomChanges] = useState({
    starAir: { state: "na" },
    akasa: { state: "na" },
    airIndia: { state: "na" },
    alliance: { state: "na" },
    indigo: { state: "na" },
  });

  const [toast, setToast] = useState(null);

  const showToast = (message, type = "info") => {
    setToast({ message, type });
    setTimeout(() => setToast(null), 3000);
  };

  // Individual airline refresh functions
  const refreshStarAir = useCallback(async () => {
    try {
      const response = await fetch(API_ENDPOINTS.STAR_AIR.LAST_STATE);
      const data = await response.json();
      if (data.success && data.data) {
        setScraperStates((prev) => ({ ...prev, starAir: data.data }));
      }
    } catch (error) {
      console.error("Error refreshing Star Air:", error);
    }
  }, []);

  const refreshAkasa = useCallback(async () => {
    try {
      const response = await fetch(API_ENDPOINTS.AKASA.LAST_STATE);
      const data = await response.json();
      if (data.success && data.data) {
        setScraperStates((prev) => ({ ...prev, akasa: data.data }));
      }
    } catch (error) {
      console.error("Error refreshing Akasa:", error);
    }
  }, []);

  const refreshAirIndia = useCallback(async () => {
    try {
      const response = await fetch(API_ENDPOINTS.AIR_INDIA.LAST_STATE);
      const data = await response.json();
      if (data.success && data.data) {
        setScraperStates((prev) => ({ ...prev, airIndia: data.data }));
      }
    } catch (error) {
      console.error("Error refreshing Air India:", error);
    }
  }, []);

  const refreshAlliance = useCallback(async () => {
    try {
      const response = await fetch(API_ENDPOINTS.ALLIANCE.LAST_STATE);
      const data = await response.json();
      if (data.success && data.data) {
        setScraperStates((prev) => ({ ...prev, alliance: data.data }));
      }
    } catch (error) {
      console.error("Error refreshing Alliance:", error);
    }
  }, []);

  const refreshIndigo = useCallback(async () => {
    try {
      const response = await fetch(API_ENDPOINTS.INDIGO.LAST_STATE);
      const data = await response.json();
      if (data.success && data.data) {
        setScraperStates((prev) => ({ ...prev, indigo: data.data }));
      }
    } catch (error) {
      console.error("Error refreshing Indigo:", error);
    }
  }, []);

  const loadScraperStatus = useCallback(async () => {
    await Promise.all([
      refreshStarAir(),
      refreshAkasa(),
      refreshAirIndia(),
      refreshAlliance(),
      refreshIndigo(),
    ]);
  }, [
    refreshStarAir,
    refreshAkasa,
    refreshAirIndia,
    refreshAlliance,
    refreshIndigo,
  ]);

  const loadDomChanges = useCallback(async () => {
    try {
      // Load Star Air DOM changes
      const starAirResponse = await fetch(API_ENDPOINTS.STAR_AIR.CHANGES);

      const starAirData = await starAirResponse.json();
      if (starAirData.success) {
        setDomChanges((prev) => ({
          ...prev,
          starAir: {
            state: starAirData.currentStatus?.has_changes
              ? "changes"
              : "no-changes",
            changes: starAirData.data,
          },
        }));
      }

      // Load Alliance DOM changes
      const allianceResponse = await fetch(API_ENDPOINTS.ALLIANCE.CHANGES);

      const allianceData = await allianceResponse.json();
      if (
        allianceData.success &&
        allianceData.data &&
        allianceData.data.changes
      ) {
        const hasChanges = allianceData.data.changes.length > 0;
        setDomChanges((prev) => ({
          ...prev,
          alliance: {
            state: hasChanges ? "changes" : "no-changes",
            changes: allianceData.data.changes,
          },
        }));
      }

      // For airlines that don't track DOM changes, keep as N/A
      setDomChanges((prev) => ({
        ...prev,
        akasa: { state: "na" },
        airIndia: { state: "na" },
        indigo: { state: "na" },
      }));
    } catch (error) {
      console.error("Error loading DOM changes:", error);
    }
  }, []);

  useEffect(() => {
    loadScraperStatus();
    loadDomChanges();
    const interval = setInterval(() => {
      loadScraperStatus();
      loadDomChanges();
    }, 30000);

    // Star Air events - all trigger a refresh
    socket.on("scraper_status", refreshStarAir);
    socket.on("settings_updated", refreshStarAir);
    socket.on("scraper_auto_run_complete", refreshStarAir);

    // Air India events - all trigger a refresh
    socket.on("air_scraper_completed", refreshAirIndia);
    socket.on("air_india_settings_updated", refreshAirIndia);
    socket.on("air_scraper_status", refreshAirIndia);

    // Akasa events - all trigger a refresh
    socket.on("akasa_scraper_completed", refreshAkasa);
    socket.on("akasa_settings_updated", refreshAkasa);
    socket.on("akasa_scraper_status", refreshAkasa);
    socket.on("akasa_scraper_state_updated", refreshAkasa);

    // Alliance events - all trigger a refresh
    socket.on("alliance_scrapper_run_completed", refreshAlliance);
    socket.on("alliance_settings_updated", refreshAlliance);
    socket.on("alliance_scraper_status", refreshAlliance);

    // Indigo events - all trigger a refresh
    socket.on("indigo_scrapper_run_completed", refreshIndigo);
    socket.on("indigo_settings_updated", refreshIndigo);
    socket.on("indigo_scraper_status", refreshIndigo);

    return () => {
      clearInterval(interval);
      // Cleanup socket listeners
      const events = [
        "scraper_status",
        "settings_updated",
        "scraper_auto_run_complete",
        "air_scraper_completed",
        "air_india_settings_updated",
        "air_scraper_status",
        "akasa_scraper_completed",
        "akasa_settings_updated",
        "akasa_scraper_status",
        "akasa_scraper_state_updated",
        "alliance_scrapper_run_completed",
        "alliance_settings_updated",
        "alliance_scraper_status",
        "indigo_scrapper_run_completed",
        "indigo_settings_updated",
        "indigo_scraper_status",
      ];
      events.forEach((event) => socket.off(event));
    };
  }, [
    socket,
    loadDomChanges,
    refreshStarAir,
    refreshAkasa,
    refreshAirIndia,
    refreshAlliance,
    refreshIndigo,
    loadScraperStatus,
  ]);

  const getStatusBadgeClass = (state) => {
    switch (state) {
      case "completed":
      case "success":
        return "bg-success";
      case "failed":
      case "error":
        return "bg-danger";
      case "running":
        return "bg-warning";
      default:
        return "bg-secondary";
    }
  };

  const renderStatusBadge = (state, error) => (
    <StatusBadge
      type={state}
      label={state === "running" ? "Running" : state || "Not Started"}
      tooltipText={state === "failed" || state === "error" ? error : undefined}
    />
  );

  const getDomBadgeClass = (state) => {
    switch (state) {
      case "changes":
        return "dom-changes";
      case "no-changes":
        return "dom-no-changes";
      default:
        return "dom-na";
    }
  };

  const renderDomChangeBadge = (airline) => {
    const domState = domChanges[airline];
    return (
      <div className="d-flex justify-content-center">
        <StatusBadge
          type={domState.state}
          label={
            domState.state === "changes"
              ? "Changes Detected"
              : domState.state === "no-changes"
              ? "No Changes"
              : "N/A"
          }
          tooltipText={
            domState.changes ? JSON.stringify(domState.changes) : undefined
          }
        />
      </div>
    );
  };

  const renderAutoRunBadge = (isEnabled) => (
    <StatusBadge
      type={isEnabled ? "enabled" : "disabled"}
      label={isEnabled ? "Enabled" : "Disabled"}
    />
  );

  const navigateToScraperPage = (type) => {
    switch (type) {
      case "indigo":
        navigate("/scrapers/indigo");
        break;
      case "akasa":
        navigate("/scrapers/akasa");
        break;
      case "alliance":
        navigate("/scrapers/alliance");
        break;
      case "starAir":
        navigate("/scrapers/star-air");
        break;
      case "airIndia":
        navigate("/scrapers/air-india");
        break;
      default:
        showToast("Unknown scraper type", "error");
    }
  };

  return (
    <div className="custom-card">
      <div className="content-header">
        <h1 className="content-title">Scrapers Monitor</h1>
      </div>

      <div className="table-container">
        <div className="table-responsive">
          <table className="table">
            <thead>
              <tr>
                <th>Scraper</th>
                <th>Last Run</th>
                <th>Current PNR</th>
                <th>Other Details</th>
                <th>Next Run</th>
                <th>Status</th>
                <th>Auto Run</th>
                <th>DOM Changes</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {/* Star Air Row */}
              <tr>
                <td>Star Air</td>
                <td>
                  {scraperStates.starAir.last_run
                    ? new Date(scraperStates.starAir.last_run).toLocaleString()
                    : "-"}
                </td>
                <td>{scraperStates.starAir.pnr || "-"}</td>
                <td>{scraperStates.starAir.gstin || "-"}</td>
                <td>
                  {scraperStates.starAir.auto_run &&
                  scraperStates.starAir.next_run
                    ? new Date(scraperStates.starAir.next_run).toLocaleString()
                    : "Not scheduled"}
                </td>
                <td>
                  {renderStatusBadge(
                    scraperStates.starAir.state,
                    scraperStates.starAir.error || scraperStates.starAir.message
                  )}
                </td>
                <td>{renderAutoRunBadge(scraperStates.starAir.auto_run)}</td>
                <td>{renderDomChangeBadge("starAir")}</td>
                <td>
                  <div className="action-icons">
                    <button
                      onClick={() => navigateToScraperPage("starAir")}
                      className="btn btn-icon"
                      title="Open Scraper"
                    >
                      <i className="bi bi-box-arrow-up-right"></i>
                    </button>
                  </div>
                </td>
              </tr>

              {/* Akasa Row */}
              <tr>
                <td>Akasa</td>
                <td>
                  {scraperStates.akasa.last_run
                    ? new Date(scraperStates.akasa.last_run).toLocaleString()
                    : "-"}
                </td>
                <td>{scraperStates.akasa.pnr || "-"}</td>
                <td>{scraperStates.akasa.traveller_name || "-"}</td>
                <td>
                  {scraperStates.akasa.auto_run && scraperStates.akasa.next_run
                    ? new Date(scraperStates.akasa.next_run).toLocaleString()
                    : "Not scheduled"}
                </td>
                <td>
                  {renderStatusBadge(
                    scraperStates.akasa.state,
                    scraperStates.akasa.error || scraperStates.akasa.message
                  )}
                </td>
                <td>{renderAutoRunBadge(scraperStates.akasa.auto_run)}</td>
                <td>{renderDomChangeBadge("akasa")}</td>
                <td>
                  <div className="action-icons">
                    <button
                      onClick={() => navigateToScraperPage("akasa")}
                      className="btn btn-icon"
                      title="Open Scraper"
                    >
                      <i className="bi bi-box-arrow-up-right"></i>
                    </button>
                  </div>
                </td>
              </tr>

              {/* Air India Row */}
              <tr>
                <td>Air India</td>
                <td>
                  {scraperStates.airIndia.last_run
                    ? new Date(scraperStates.airIndia.last_run).toLocaleString()
                    : "-"}
                </td>
                <td>{scraperStates.airIndia.pnr || "-"}</td>
                <td>
                  Origin: {scraperStates.airIndia.origin || "-"} | Vendor:{" "}
                  {scraperStates.airIndia.vendor || "-"}
                </td>
                <td>
                  {scraperStates.airIndia.auto_run &&
                  scraperStates.airIndia.next_run
                    ? new Date(scraperStates.airIndia.next_run).toLocaleString()
                    : "Not scheduled"}
                </td>
                <td>
                  {renderStatusBadge(
                    scraperStates.airIndia.state,
                    scraperStates.airIndia.error ||
                      scraperStates.airIndia.message
                  )}
                </td>
                <td>{renderAutoRunBadge(scraperStates.airIndia.auto_run)}</td>
                <td>{renderDomChangeBadge("airIndia")}</td>
                <td>
                  <div className="action-icons">
                    <button
                      onClick={() => navigateToScraperPage("airIndia")}
                      className="btn btn-icon"
                      title="Open Scraper"
                    >
                      <i className="bi bi-box-arrow-up-right"></i>
                    </button>
                  </div>
                </td>
              </tr>

              {/* Alliance Row */}
              <tr>
                <td>Alliance</td>
                <td>
                  {scraperStates.alliance.last_run
                    ? new Date(scraperStates.alliance.last_run).toLocaleString()
                    : "-"}
                </td>
                <td>{scraperStates.alliance.pnr || "-"}</td>
                <td>
                  Transaction Date:{" "}
                  {scraperStates.alliance.transaction_date || "-"}
                </td>
                <td>
                  {scraperStates.alliance.auto_run &&
                  scraperStates.alliance.next_run
                    ? new Date(scraperStates.alliance.next_run).toLocaleString()
                    : "Not scheduled"}
                </td>
                <td>
                  {renderStatusBadge(
                    scraperStates.alliance.state,
                    scraperStates.alliance.error ||
                      scraperStates.alliance.message
                  )}
                </td>
                <td>{renderAutoRunBadge(scraperStates.alliance.auto_run)}</td>
                <td>{renderDomChangeBadge("alliance")}</td>
                <td>
                  <div className="action-icons">
                    <button
                      onClick={() => navigateToScraperPage("alliance")}
                      className="btn btn-icon"
                      title="Open Scraper"
                    >
                      <i className="bi bi-box-arrow-up-right"></i>
                    </button>
                  </div>
                </td>
              </tr>

              {/* Indigo Row */}
              <tr>
                <td>Indigo</td>
                <td>
                  {scraperStates.indigo.timestamp
                    ? new Date(scraperStates.indigo.timestamp).toLocaleString()
                    : "-"}
                </td>
                <td>{scraperStates.indigo.pnr || "-"}</td>
                <td>Email: {scraperStates.indigo.ssr_email || "-"}</td>
                <td>
                  {scraperStates.indigo.auto_run &&
                  scraperStates.indigo.next_run
                    ? new Date(scraperStates.indigo.next_run).toLocaleString()
                    : "Not scheduled"}
                </td>
                <td>
                  {renderStatusBadge(
                    scraperStates.indigo.state,
                    scraperStates.indigo.error || scraperStates.indigo.message
                  )}
                </td>
                <td>{renderAutoRunBadge(scraperStates.indigo.auto_run)}</td>
                <td>{renderDomChangeBadge("indigo")}</td>
                <td>
                  <div className="action-icons">
                    <button
                      onClick={() => navigateToScraperPage("indigo")}
                      className="btn btn-icon"
                      title="Open Scraper"
                    >
                      <i className="bi bi-box-arrow-up-right"></i>
                    </button>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
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
    </div>
  );
};

export default Scrapers;
