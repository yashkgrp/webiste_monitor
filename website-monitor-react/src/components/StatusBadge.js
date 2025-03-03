import React from "react";
import "./StatusBadge.css";

const StatusBadge = ({ type, label, tooltipText }) => {
  const getTypeClass = () => {
    switch (type) {
      case "success":
      case "up":
      case "completed":
      case "no-changes":
      case "enabled":
        return "status-success";
      case "error":
      case "down":
      case "failed":
      case "changes":
      case "disabled":
        return "status-error";
      case "warning":
      case "slow":
      case "running":
        return "status-warning";
      case "na":
      default:
        return "status-neutral";
    }
  };

  const getIcon = () => {
    switch (type) {
      case "success":
      case "up":
      case "completed":
      case "no-changes":
      case "enabled":
        return (
          <svg
            width="14"
            height="14"
            viewBox="0 0 14 14"
            fill="none"
            xmlns="http://www.w3.org/2000/svg"
          >
            <path
              d="M11.6667 3.5L5.25 9.91667L2.33333 7"
              stroke="currentColor"
              strokeWidth="1.2"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
        );
      case "error":
      case "down":
      case "failed":
        return (
          <svg
            width="14"
            height="14"
            viewBox="0 0 14 14"
            fill="none"
            xmlns="http://www.w3.org/2000/svg"
          >
            <path
              d="M10.5 3.5L3.5 10.5M3.5 3.5L10.5 10.5"
              stroke="currentColor"
              strokeWidth="1.2"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
        );
      case "warning":
      case "slow":
      case "running":
      case "changes":
      case "disabled":
        return (
          <svg
            width="14"
            height="14"
            viewBox="0 0 14 14"
            fill="none"
            xmlns="http://www.w3.org/2000/svg"
          >
            <path
              d="M7 5.25V7.58333M7 9.91667H7.00667M12.8333 7C12.8333 10.2217 10.2217 12.8333 7 12.8333C3.77834 12.8333 1.16667 10.2217 1.16667 7C1.16667 3.77834 3.77834 1.16667 7 1.16667C10.2217 1.16667 12.8333 3.77834 12.8333 7Z"
              stroke="currentColor"
              strokeWidth="1.2"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
        );
      default:
        return (
          <svg
            width="14"
            height="14"
            viewBox="0 0 14 14"
            fill="none"
            xmlns="http://www.w3.org/2000/svg"
          >
            <circle
              cx="7"
              cy="7"
              r="6"
              stroke="currentColor"
              strokeWidth="1.2"
            />
            <path
              d="M7 4V7.5M7 10H7.007"
              stroke="currentColor"
              strokeWidth="1.2"
              strokeLinecap="round"
            />
          </svg>
        );
    }
  };

  return (
    <span className={`status-badge ${getTypeClass()}`} title={tooltipText}>
      <span className="status-icon">{getIcon()}</span>
      <span className="status-label">{label}</span>
    </span>
  );
};

export default StatusBadge;
