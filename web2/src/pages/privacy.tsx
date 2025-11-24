import React from "react";
import ReactDOM from "react-dom/client";
import { DocsLayout } from "../sections/DocsLayout";
import { privacySections } from "../data/docs";
import "../styles.css";

ReactDOM.createRoot(document.getElementById("root") as HTMLElement).render(
  <React.StrictMode>
    <DocsLayout title="Privacy" description="How plexdev.live handles telemetry, analytics, and data removal requests." sections={privacySections} />
  </React.StrictMode>
);
