import React, { useState, useEffect, useRef } from "react";
import Chart from "chart.js/auto";
import "bootstrap/dist/js/bootstrap.bundle.min.js";
import { API_BASE_URL } from "../config";
const Analytics = ({ url, show, onHide }) => {
  const [loading, setLoading] = useState(true);
  const [analyticsData, setAnalyticsData] = useState(null);
  const [totalChecks, setTotalChecks] = useState(0);
  const [currentOffset, setCurrentOffset] = useState(0);
  const [hasMoreData, setHasMoreData] = useState(true);
  const [selectedInterval, setSelectedInterval] = useState(1);
  const [showQuickView, setShowQuickView] = useState(false);
  const activeChartRef = useRef(null);

  useEffect(() => {
    if (show && url) {
      setCurrentOffset(0);
      setHasMoreData(true);
      loadAnalyticsData();
    }
    return () => {
      if (activeChartRef.current) {
        activeChartRef.current.destroy();
      }
    };
  }, [show, url]);

  useEffect(() => {
    if (analyticsData && !loading) {
      updateCharts();
    }
  }, [analyticsData, loading, selectedInterval, showQuickView]);

  const loadAnalyticsData = async () => {
    try {
      setLoading(true);
      const response = await fetch(
        `${API_BASE_URL}/get_url_history/${encodeURIComponent(
          url
        )}?offset=${currentOffset}`
      );

      if (!response.ok) {
        throw new Error("Failed to load analytics data");
      }

      const result = await response.json();

      if (result.status === "success") {
        if (currentOffset === 0) {
          setAnalyticsData(result.data);
          setTotalChecks(result.data.analysis.reliability.total_checks);
        } else {
          setAnalyticsData((prev) => ({
            ...prev,
            history: [...prev.history, ...result.data.history],
          }));
        }
        setHasMoreData(result.data.has_more);
      } else {
        throw new Error(result.error || "Failed to load analytics data");
      }
    } catch (error) {
      console.error("Error loading analytics:", error);
    } finally {
      setLoading(false);
    }
  };

  const loadMoreData = async () => {
    if (!hasMoreData) return;

    const button = document.getElementById("loadMoreBtn");
    if (button) {
      button.disabled = true;
      button.innerHTML =
        '<span class="spinner-border spinner-border-sm"></span> Loading...';
    }

    setCurrentOffset((prev) => prev + 5000);
    await loadAnalyticsData();

    if (button) {
      button.disabled = false;
      button.textContent = "Load More Data";
    }
  };

  const updateCharts = () => {
    if (!analyticsData) return;

    const stats = analyticsData.analysis.reliability;
    const hourlyData = analyticsData.analysis.avg_response_by_hour;
    const groupedData = groupDataByInterval(
      analyticsData.history,
      selectedInterval
    );

    if (activeChartRef.current) {
      activeChartRef.current.destroy();
    }

    const chartCtx = document.getElementById("responseChart");
    if (chartCtx) {
      if (showQuickView) {
        activeChartRef.current = new Chart(chartCtx, {
          type: "bar",
          data: {
            labels: hourlyData.map((d) => `${d.hour}:00`),
            datasets: [
              {
                label: "Average Response Time (ms)",
                data: hourlyData.map((d) => d.avg_response_time),
                backgroundColor: "rgba(10, 131, 148, 0.5)",
                borderColor: "rgb(10, 131, 148)",
                borderWidth: 1,
              },
            ],
          },
          options: {
            responsive: true,
            maintainAspectRatio: false,
            scales: {
              y: {
                beginAtZero: true,
                title: {
                  display: true,
                  text: "Response Time (ms)",
                  font: {
                    family: "'Noto Sans', system-ui, -apple-system, sans-serif",
                  },
                },
                ticks: {
                  callback: (value) => `${value} ms`,
                  font: {
                    family: "'Noto Sans', system-ui, -apple-system, sans-serif",
                  },
                },
              },
              x: {
                ticks: {
                  font: {
                    family: "'Noto Sans', system-ui, -apple-system, sans-serif",
                  },
                },
              },
            },
            plugins: {
              tooltip: {
                callbacks: {
                  label: (context) => `Average Response: ${context.raw} ms`,
                },
                titleFont: {
                  family: "'Noto Sans', system-ui, -apple-system, sans-serif",
                },
                bodyFont: {
                  family: "'Noto Sans', system-ui, -apple-system, sans-serif",
                },
              },
              legend: {
                labels: {
                  font: {
                    family: "'Noto Sans', system-ui, -apple-system, sans-serif",
                  },
                },
              },
            },
          },
        });
      } else {
        activeChartRef.current = new Chart(chartCtx, {
          type: "line",
          data: {
            labels: groupedData.map((d) =>
              new Date(d.timestamp).toLocaleString()
            ),
            datasets: [
              {
                label: `Response Time (${formatInterval(
                  selectedInterval
                )} intervals)`,
                data: groupedData.map((d) => d.response_time.toFixed(2)),
                borderColor: "rgb(10, 131, 148)",
                backgroundColor: "rgba(10, 131, 148, 0.1)",
                tension: 0.1,
                pointRadius: 2,
              },
            ],
          },
          options: {
            responsive: true,
            maintainAspectRatio: false,
            scales: {
              y: {
                beginAtZero: true,
                title: {
                  display: true,
                  text: "Response Time (ms)",
                  font: {
                    family: "'Noto Sans', system-ui, -apple-system, sans-serif",
                  },
                },
                ticks: {
                  callback: (value) => `${value} ms`,
                  font: {
                    family: "'Noto Sans', system-ui, -apple-system, sans-serif",
                  },
                },
              },
              x: {
                ticks: {
                  maxRotation: 45,
                  minRotation: 45,
                  autoSkip: true,
                  maxTicksLimit: 20,
                  font: {
                    family: "'Noto Sans', system-ui, -apple-system, sans-serif",
                  },
                },
              },
            },
            plugins: {
              tooltip: {
                callbacks: {
                  label: (context) => {
                    const data = groupedData[context.dataIndex];
                    return [
                      `Response Time: ${data.response_time.toFixed(2)} ms`,
                      `Samples in interval: ${data.count}`,
                      `Uptime: ${data.uptime.toFixed(1)}%`,
                    ];
                  },
                },
                titleFont: {
                  family: "'Noto Sans', system-ui, -apple-system, sans-serif",
                },
                bodyFont: {
                  family: "'Noto Sans', system-ui, -apple-system, sans-serif",
                },
              },
              legend: {
                labels: {
                  font: {
                    family: "'Noto Sans', system-ui, -apple-system, sans-serif",
                  },
                },
              },
            },
          },
        });
      }
    }
  };

  const groupDataByInterval = (data, intervalMinutes) => {
    if (!data || data.length === 0) return [];

    const sortedData = data.sort((a, b) => a.timestamp - b.timestamp);
    const startTime = sortedData[0].timestamp * 1000;
    const endTime = sortedData[sortedData.length - 1].timestamp * 1000;
    const intervalMs = intervalMinutes * 60 * 1000;
    const groups = new Map();

    for (let time = startTime; time <= endTime; time += intervalMs) {
      groups.set(time, { times: [], statuses: [] });
    }

    sortedData.forEach((entry) => {
      const entryTime = entry.timestamp * 1000;
      const intervalStart =
        startTime +
        Math.floor((entryTime - startTime) / intervalMs) * intervalMs;
      const group = groups.get(intervalStart);
      if (group) {
        group.times.push(entry.response_time);
        group.statuses.push(entry.status);
      }
    });

    return Array.from(groups.entries())
      .filter(([_, group]) => group.times.length > 0)
      .map(([timestamp, group]) => ({
        timestamp,
        response_time:
          group.times.reduce((a, b) => a + b, 0) / group.times.length,
        count: group.times.length,
        uptime:
          (group.statuses.filter((s) => s.includes("Up")).length /
            group.statuses.length) *
          100,
      }));
  };

  const formatInterval = (minutes) => {
    if (minutes < 60) return `${minutes} min`;
    if (minutes < 1440)
      return `${minutes / 60} hour${minutes / 60 > 1 ? "s" : ""}`;
    if (minutes < 10080)
      return `${minutes / 1440} day${minutes / 1440 > 1 ? "s" : ""}`;
    return `${minutes / 10080} week${minutes / 10080 > 1 ? "s" : ""}`;
  };

  return (
    <>
      <div
        className={`modal fade ${show ? "show" : ""}`}
        id="analyticsModal"
        tabIndex="-1"
        style={{ display: show ? "block" : "none" }}
      >
        <div className="modal-dialog modal-xl">
          <div className="modal-content">
            <div className="modal-header">
              <h5 className="modal-title">URL Analytics Dashboard</h5>
              <button
                type="button"
                className="btn-close"
                onClick={onHide}
              ></button>
            </div>
            <div
              className="modal-body"
              style={{ backgroundColor: "var(--gray-100)", padding: "1.5rem" }}
            >
              {loading ? (
                <div id="analyticsSpinner" className="text-center my-3">
                  <div className="spinner-border text-primary" role="status">
                    <span className="visually-hidden">Loading...</span>
                  </div>
                  <p className="mt-2">Loading analytics data...</p>
                </div>
              ) : (
                <div id="analyticsContent" style={{ padding: "0.5rem" }}>
                  {analyticsData && (
                    <div className="card">
                      <div className="card-body">
                        {/* Reliability Stats Section */}
                        <h5 className="card-title mb-4">Reliability Stats</h5>
                        <div className="row mb-4" id="reliabilityStats">
                          <div
                            className="col-md-4"
                            style={{ borderRight: "1px solid var(--gray-200)" }}
                          >
                            <div className="row mb-3">
                              <div className="col-12">
                                <p className="mb-2">
                                  <strong>Uptime:</strong>{" "}
                                  <span className="text-success">
                                    {analyticsData.analysis.reliability.uptime}%
                                  </span>
                                </p>
                              </div>
                            </div>
                            <div className="row">
                              <div className="col-12">
                                <p className="mb-2">
                                  <strong>Avg Response:</strong>{" "}
                                  <span>
                                    {
                                      analyticsData.analysis.reliability
                                        .avg_response
                                    }{" "}
                                    ms
                                  </span>
                                </p>
                              </div>
                            </div>
                          </div>
                          <div
                            className="col-md-4"
                            style={{ borderRight: "1px solid var(--gray-200)" }}
                          >
                            <div className="row mb-3">
                              <div className="col-12">
                                <p className="mb-2">
                                  <strong>Last Down:</strong>{" "}
                                  <span className="text-danger">
                                    {analyticsData.analysis.reliability
                                      .last_down_period || "Never"}
                                  </span>
                                </p>
                              </div>
                            </div>
                            <div className="row">
                              <div className="col-12">
                                <p className="mb-2">
                                  <strong>Last Slow:</strong>{" "}
                                  <span className="text-warning">
                                    {analyticsData.analysis.reliability
                                      .last_slow_period || "Never"}
                                  </span>
                                </p>
                              </div>
                            </div>
                          </div>
                          <div className="col-md-4">
                            <div className="row mb-3">
                              <div className="col-12">
                                <p className="mb-2">
                                  <strong>Total Checks:</strong>{" "}
                                  <span>{totalChecks}</span>
                                </p>
                              </div>
                            </div>
                            <div className="row">
                              <div className="col-12">
                                <p className="mb-2">
                                  <strong>Data Age:</strong>{" "}
                                  <span>
                                    {(
                                      (Date.now() -
                                        Math.min(
                                          ...analyticsData.history.map(
                                            (entry) => entry.timestamp * 1000
                                          )
                                        )) /
                                      (1000 * 60 * 60)
                                    ).toFixed(1)}{" "}
                                    hours
                                  </span>
                                </p>
                              </div>
                            </div>
                          </div>
                        </div>

                        {/* Controls Section - Modified */}
                        <div
                          className="row mb-4"
                          style={{
                            borderTop: "1px solid var(--gray-200)",
                            padding: "0.75rem 0",
                          }}
                        >
                          <div className="col-md-6 d-flex align-items-center">
                            <span
                              className="me-3"
                              style={{
                                fontWeight: "550",
                              }}
                            >
                              {showQuickView
                                ? "Response Time by Hour"
                                : "Response Time History"}
                            </span>
                            <div className="form-check form-switch">
                              <input
                                className="form-check-input"
                                type="checkbox"
                                id="quickViewToggle"
                                checked={showQuickView}
                                onChange={(e) =>
                                  setShowQuickView(e.target.checked)
                                }
                                style={{
                                  backgroundColor: showQuickView
                                    ? "var(--teal-primary)"
                                    : "",
                                  borderColor: "var(--teal-primary)",
                                }}
                              />
                            </div>
                          </div>
                          <div className="col-md-6 d-flex justify-content-end align-items-center gap-3">
                            {!showQuickView && (
                              <div style={{ width: "200px" }}>
                                <select
                                  className="form-select"
                                  id="timeInterval"
                                  value={selectedInterval}
                                  onChange={(e) =>
                                    setSelectedInterval(Number(e.target.value))
                                  }
                                  style={{
                                    borderColor: "var(--teal-primary)",
                                    borderRadius: "8px",
                                    color: "var(--teal-primary)",
                                    fontWeight: "500",
                                  }}
                                >
                                  <optgroup label="Minutes">
                                    <option value="1">1 minute</option>
                                    <option value="5">5 minutes</option>
                                    <option value="10">10 minutes</option>
                                    <option value="15">15 minutes</option>
                                    <option value="30">30 minutes</option>
                                  </optgroup>
                                  <optgroup label="Hours">
                                    <option value="60">1 hour</option>
                                    <option value="180">3 hours</option>
                                    <option value="360">6 hours</option>
                                    <option value="720">12 hours</option>
                                  </optgroup>
                                  <optgroup label="Days">
                                    <option value="1440">1 day</option>
                                    <option value="4320">3 days</option>
                                    <option value="10080">1 week</option>
                                  </optgroup>
                                </select>
                              </div>
                            )}
                            {hasMoreData && (
                              <button
                                className="btn btn-primary"
                                id="loadMoreBtn"
                                onClick={loadMoreData}
                              >
                                Load More Data
                              </button>
                            )}
                          </div>
                        </div>

                        {/* Chart Section - Modified */}
                        <div style={{ height: "400px" }}>
                          <canvas id="responseChart"></canvas>
                        </div>
                      </div>
                    </div>
                  )}
                </div>
              )}
            </div>
          </div>
        </div>
      </div>
      {show && <div className="modal-backdrop show"></div>}
    </>
  );
};

export default Analytics;
