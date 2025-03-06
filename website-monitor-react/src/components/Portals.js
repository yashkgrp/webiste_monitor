import React, { useState, useEffect } from "react";
import StatusBadge from "./StatusBadge";
import "./IndigoScraper.css";

const Portals = () => {
  // Demo data for the portals
  const [portalData] = useState([
    {
      name: "Portal 1",
      lastAccessed: "2024-01-20 10:30:00",
      currentUser: "John Doe",
      domain: "portal1.example.com",
      status: "active",
      autoLogin: true,
      lastSync: "2024-01-20 10:25:00",
    },
    {
      name: "Portal 2",
      lastAccessed: "2024-01-20 09:15:00",
      currentUser: "Jane Smith",
      domain: "portal2.example.com",
      status: "inactive",
      autoLogin: false,
      lastSync: "2024-01-20 09:10:00",
    },
    {
      name: "Portal 3",
      lastAccessed: "2024-01-20 11:45:00",
      currentUser: "Mike Johnson",
      domain: "portal3.example.com",
      status: "maintenance",
      autoLogin: true,
      lastSync: "2024-01-20 11:40:00",
    },
  ]);

  const renderStatusBadge = (status) => (
    <StatusBadge
      type={status}
      label={status.charAt(0).toUpperCase() + status.slice(1)}
    />
  );

  const renderAutoLoginBadge = (isEnabled) => (
    <StatusBadge
      type={isEnabled ? "enabled" : "disabled"}
      label={isEnabled ? "Enabled" : "Disabled"}
    />
  );

  return (
    <div className="custom-card">
      <div className="content-header">
        <h1 className="content-title">Portals Monitor</h1>
      </div>

      <div className="table-container">
        <div className="table-responsive">
          <table className="table">
            <thead>
              <tr>
                <th>Portal Name</th>
                <th>Last Accessed</th>
                <th>Current User</th>
                <th>Domain</th>
                <th>Status</th>
                <th>Auto Login</th>
                <th>Last Sync</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {portalData.map((portal, index) => (
                <tr key={index}>
                  <td>{portal.name}</td>
                  <td>{portal.lastAccessed}</td>
                  <td>{portal.currentUser}</td>
                  <td>{portal.domain}</td>
                  <td>{renderStatusBadge(portal.status)}</td>
                  <td>{renderAutoLoginBadge(portal.autoLogin)}</td>
                  <td>{portal.lastSync}</td>
                  <td>
                    <div className="action-icons">
                      <button className="btn btn-icon" title="Open Portal">
                        <i className="bi bi-box-arrow-up-right"></i>
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
  );
};

export default Portals;
