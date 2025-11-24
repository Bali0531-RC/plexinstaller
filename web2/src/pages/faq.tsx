import React from "react";
import ReactDOM from "react-dom/client";
import { DocsLayout } from "../sections/DocsLayout";
import { faqSections } from "../data/docs";
import "../styles.css";

ReactDOM.createRoot(document.getElementById("root") as HTMLElement).render(
  <React.StrictMode>
    <DocsLayout title="Frequently Asked Questions" description="Answers to the most common PlexDev Installer questions." sections={faqSections} />
  </React.StrictMode>
);
