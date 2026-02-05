export type ReleaseNote = {
  version: string;
  date: string;
  highlights: string[];
};

export const releases: ReleaseNote[] = [
  {
    version: "3.1.13",
    date: "2026-02-05",
    highlights: [
      "Domain migration from plexdev.live to plexdev.xyz.",
      "Updated all URLs, endpoints, and references to use new domain.",
      "Added migration notice banner on website.",
      "Old domain (plexdev.live) now permanently redirects to plexdev.xyz."
    ]
  },
  {
    version: "3.1.12",
    date: "2026-01-16",
    highlights: [
      "Added Addon Management for PlexTickets and PlexStaff products.",
      "Addons can be installed from .zip/.rar archives with smart extraction handling.",
      "Smart extraction handles both correctly packaged (single folder) and incorrectly packaged (loose files) addons.",
      "Addon configuration editing with YAML syntax validation.",
      "Automatic backup creation before addon removal.",
      "New TUI menu: 'Manage Addons' for interactive addon management.",
      "New CLI commands: plex addon list|install|remove|config."
    ]
  },
  {
    version: "3.1.11",
    date: "2025-12-17",
    highlights: [
      "Added PlexTracker as a supported product (default port 3007).",
      "MongoDB provisioning is now more reliable: waits for mongod readiness and idempotently creates/updates per-instance DB users.",
      "Installer validates MongoDB credentials by authenticating with the generated URI before continuing.",
      "Post-install self-tests now verify Node version, systemd service health, local port/HTTP response, nginx wiring, and MongoDB auth (DNS/HTTPS checks are warnings only).",
      "MongoDB URI injection now supports config.json in addition to config.yml/config.yaml."
    ]
  },
  {
    version: "3.1.10",
    date: "2025-12-12",
    highlights: [
      "Fixed plex CLI autoupdates by ensuring the setup installs /usr/local/bin/plex as a symlink to /opt/plexinstaller/plex_cli.py.",
      "Running 'plex' now checks for installer updates too (same auto-update prompt behavior as plexinstaller).",
      "Added 'plex debug <app>' to upload redacted config.yml + last 500 journalctl lines to the paste service.",
      "Debug command supports multi-instance installs (e.g. plextickets-ab12) and redacts Token, LicenseKey, SecretKey, and MongoURI values (including MongoDB URI credentials)."
    ]
  },
  {
    version: "3.1.9",
    date: "2025-11-25",
    highlights: [
      "Setup script now installs requests module so telemetry works out of the box.",
      "RAR extraction validates paths post-extraction to block directory traversal.",
      "MongoDB shell fallback handles missing mongosh/mongo gracefully instead of crashing.",
      "Telemetry server uses file locking to prevent concurrent write corruption.",
      "Archive extraction shows user-friendly errors for corrupted or inaccessible files.",
      "Fixed SystemdManager.get_status to catch exceptions correctly."
    ]
  },
  {
    version: "3.1.8",
    date: "2025-11-25",
    highlights: [
      "Auto-updates now verify SHA256 checksums before applying downloaded files.",
      "Lock file prevents multiple installer instances from running concurrently.",
      "Root check moved before telemetry prompt so preferences save correctly on first run.",
      "Archive extraction validates paths to prevent directory traversal attacks.",
      "All subprocess calls now have timeouts to prevent hung processes.",
      "Input validation for port (1-65535), domain format, and email format."
    ]
  },
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
      "Updated support flows (mailto + GitHub issues) and release timeline details on plexdev.xyz.",
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
