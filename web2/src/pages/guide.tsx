import React from "react";
import ReactDOM from "react-dom/client";
import { DocsLayout } from "../sections/DocsLayout";
import { guideSections } from "../data/docs";
import "../styles.css";

ReactDOM.createRoot(document.getElementById("root") as HTMLElement).render(
  <React.StrictMode>
    <DocsLayout title="Installation Guide" description="Step-by-step walkthrough for deploying PlexDevelopment products on your own hardware." sections={guideSections} />
  </React.StrictMode>
);
