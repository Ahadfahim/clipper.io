import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "./styles/index.css";

function App() {
  return <main className="p-4 text-[12px]">Clipper</main>;
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
