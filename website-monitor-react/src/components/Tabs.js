import React from "react";
import "./Tabs.css";

const Tabs = ({ tabs, activeTab, onTabChange }) => {
  return (
    <div className="mb-4">
      <ul className="nav nav-tabs custom-tabs">
        {tabs.map((tab) => (
          <li className="nav-item" key={tab.id}>
            <button
              className={`nav-link ${activeTab === tab.id ? "active" : ""}`}
              onClick={() => onTabChange(tab.id)}
            >
              {tab.label}
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
};

export default Tabs;
