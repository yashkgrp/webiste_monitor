// API Configuration
export const API_BASE_URL =
  process.env.REACT_APP_API_BASE_URL || "https://monitor.finkraftai.com/";

// Socket Configuration
export const SOCKET_CONFIG = {
  url:
    process.env.REACT_APP_SOCKET_URL ||
    process.env.REACT_APP_API_BASE_URL ||
    "https://localhost:5000",
  options: {
    transports: ["websocket"],
    reconnection: true,
    reconnectionAttempts: 5,
    reconnectionDelay: 1000,
  },
};
