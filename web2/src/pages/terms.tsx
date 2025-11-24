import React from "react";
import ReactDOM from "react-dom/client";
import { DocsLayout } from "../sections/DocsLayout";
import { termsSections } from "../data/docs";
import "../styles.css";

ReactDOM.createRoot(document.getElementById("root") as HTMLElement).render(
  <React.StrictMode>
    <DocsLayout title="Terms of Use" description="Understand the boundaries and responsibilities when using the unofficial PlexDev Installer." sections={termsSections} />
  </React.StrictMode>
);
