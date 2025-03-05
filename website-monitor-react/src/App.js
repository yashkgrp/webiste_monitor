import { useState, useEffect } from "react";
import {
  BrowserRouter as Router,
  Routes,
  Route,
  Link,
  useLocation,
} from "react-router-dom";
import io from "socket.io-client";
import { SOCKET_CONFIG } from "./config";
import "bootstrap/dist/css/bootstrap.min.css";
import "bootstrap-icons/font/bootstrap-icons.css";
import "./App.css";
import URLMonitor from "./components/URLMonitor";
import Scrapers from "./components/Scrapers";
import IndigoScraper from "./components/IndigoScraper";
import AkasaScraper from "./components/AkasaScraper";
import AllianceScraper from "./components/AllianceScraper";
import StarAirScraper from "./components/StarAirScraper";
import AirIndiaScraper from "./components/AirIndiaScraper";
import Portals from "./components/Portals";
import { API_BASE_URL } from "./config";

// Initialize socket connection with config
const socket = io(API_BASE_URL);

function NavContent() {
  const [connectionStatus, setConnectionStatus] = useState("connecting");
  const location = useLocation();
  const activeSection = location.pathname === "/" 
    ? "urlMonitor" 
    : location.pathname === "/scrapers" 
      ? "scrapers" 
      : location.pathname === "/portals" 
        ? "portals" 
        : "";

  useEffect(() => {
    // Socket event listeners
    socket.on("connect", () => {
      setConnectionStatus("connected");
    });
    socket.on("disconnect", () => {
      setConnectionStatus("disconnected");
    });
    socket.on("connect_error", () => {
      setConnectionStatus("disconnected");
    });

    // Reconnection handling
    const reconnectionInterval = setInterval(() => {
      if (!socket.connected) {
        setConnectionStatus("connecting");
        socket.connect();
      }
    }, 5000);

    // Cleanup on unmount
    return () => {
      clearInterval(reconnectionInterval);
      socket.off("connect");
      socket.off("disconnect");
      socket.off("connect_error");
    };
  }, []);

  return (
    <>
      {/* Navigation */}
      <nav className="nav-container">
        <div className="nav-header">
          <i
            className="bi bi-speedometer2"
            style={{ fontSize: "1.75rem", color: "var(--teal-primary)" }}
          ></i>
        </div>
        <div className="nav-menu">
          <Link
            to="/"
            className={`nav-item ${
              activeSection === "urlMonitor" ? "active" : ""
            }`}
          >
            <i className="bi bi-globe"></i>
            <span>URL Monitor</span>
          </Link>
          <Link
            to="/scrapers"
            className={`nav-item ${
              activeSection === "scrapers" ? "active" : ""
            }`}
          >
            <i className="bi bi-robot"></i>
            <span>Scrapers</span>
          </Link>
          <Link
            to="/portals"
            className={`nav-item ${
              activeSection === "portals" ? "active" : ""
            }`}
          >
            <i className="bi bi-grid-3x3-gap"></i>
            <span>Portals</span>
          </Link>
        </div>
        <div className="nav-footer">
          <div
            className={`connection-indicator indicator-${connectionStatus}`}
          ></div>
        </div>
      </nav>

      {/* Main Content */}
      <main className="main-content">
        <Routes>
          <Route path="/" element={<URLMonitor socket={socket} />} />
          <Route
            path="/scrapers"
            element={
              <>
                <Scrapers socket={socket} />
              </>
            }
          />
          <Route
            path="/scrapers/indigo"
            element={<IndigoScraper socket={socket} />}
          />
          <Route
            path="/scrapers/akasa"
            element={<AkasaScraper socket={socket} />}
          />
          <Route
            path="/scrapers/alliance"
            element={<AllianceScraper socket={socket} />}
          />
          <Route
            path="/scrapers/star-air"
            element={<StarAirScraper socket={socket} />}
          />
          <Route
            path="/scrapers/air-india"
            element={<AirIndiaScraper socket={socket} />}
          />
          <Route path="/portals" element={<Portals />} />
        </Routes>
      </main>
    </>
  );
}

function App() {
  return (
    <Router>
      <NavContent />
    </Router>
  );
}

export default App;
