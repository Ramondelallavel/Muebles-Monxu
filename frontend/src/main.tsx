import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import "./styles.css";

if (import.meta.env.VITE_LOCAL === "1") document.body.classList.add("framed");

createRoot(document.getElementById("root")!).render(<StrictMode><App /></StrictMode>);
