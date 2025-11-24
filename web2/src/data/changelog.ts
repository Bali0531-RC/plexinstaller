export type ReleaseNote = {
  version: string;
  date: string;
  highlights: string[];
};

export const releases: ReleaseNote[] = [
  {
    version: "3.1.7",
    date: "2025-11-24",
    highlights: [
      "Installer now tracks each install attempt with step-by-step telemetry, auto-uploading failure logs and cleaning up partial deployments.",
      "Mobile tweaks keep command snippets and tabs contained on smaller screens, plus product blurbs and docs now reflect the correct Plex product behavior.",
      "New FastAPI telemetry collector ships in /telemetry so self-hosters can aggregate success/failure metrics and view captured logs."
    ]
  },
  {
    version: "3.1.6",
    date: "2025-11-23",
    highlights: [
      "Guide, FAQ, terms, and privacy pages now share the same React/Vite design and nav as the homepage.",
      "Updated support flows (mailto + GitHub issues) and release timeline details on plexdev.live.",
      "Installer archive discovery is now case-insensitive so files like PlexStaff-Unobf.zip are detected automatically."
    ]
  },
  {
    version: "3.1.5",
    date: "2025-11-22",
    highlights: [
      "Added Vite-powered dashboard experience at /web2.",
      "Improved MongoDB 8.x replica init reliability.",
      "Auto-update channel now retries with exponential backoff."
    ]
  },
  {
    version: "3.1.0",
    date: "2025-11-21",
    highlights: [
      "New Python installer parity with legacy bash scripts.",
      "Color-coded CLI with summary cards and health checks.",
      "Faster dependency resolution on Ubuntu and Debian."
    ]
  },
  {
    version: "2.9.4",
    date: "2025-10-02",
    highlights: [
      "Integrated MongoDB Ops Manager hooks.",
      "Added PlexStatus widgets to monitoring bundle.",
      "Docs refresh plus FAQ linking to new knowledge base."
    ]
  }
];
