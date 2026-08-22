import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";

// Inter, self-hosted. `index.css` has always asked for it, but nothing ever
// loaded it, so every machine without Inter installed silently fell back -
// and the fallback rendered a capital A as a backslash ("Active" -> "\ctive").
// Only the four weights the app actually uses.
import "@fontsource/inter/400.css";
import "@fontsource/inter/500.css";
import "@fontsource/inter/600.css";
import "@fontsource/inter/700.css";

import App from "./App";
import "./index.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <BrowserRouter>
      <App />
    </BrowserRouter>
  </StrictMode>,
);
