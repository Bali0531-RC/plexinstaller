import { DocsSection } from "../sections/DocsLayout";

export const guideSections: DocsSection[] = [
  {
    title: "Before you start",
    paragraphs: [
      "Use a dedicated Linux host with root or sudo access. Ubuntu and Debian are the primary tested targets; the code has package-manager paths for some RPM, Arch, and openSUSE-family systems, but those paths are not guaranteed.",
      "Upload the PlexTickets, PlexStaff, or Drako product archives you own to /opt/plexapps or any path you prefer—the installer never bundles them for you."
    ],
    bullets: [
      "Open only the product port you select, or use the optional nginx/domain flow rather than exposing every default port.",
      "Point your domain’s DNS records before enabling HTTPS inside products.",
      "Keep the PlexDevelopment archives and license keys you own staged before launching the installer."
    ]
  },
  {
    title: "One-line quick install",
    paragraphs: [
      "Run curl -fsSL https://plexdev.xyz/setup.sh | sudo bash. setup.sh installs bootstrap prerequisites, downloads and verifies the Python installer bundle, installs its Python requirements, and creates the plexinstaller and plex command links.",
      "setup.sh does not install MongoDB, unpack a product, configure nginx, or create product systemd units. At the end it can launch plexinstaller; otherwise run sudo plexinstaller later and follow the interactive product workflow."
    ],
    bullets: [
      "Use --insecure-beta only if you explicitly want the dev branch and accept that failed beta verification may be bypassed.",
      "On first interactive launch, choose whether to enable installer telemetry before selecting a product."
    ]
  },
  {
    title: "Manual install flow",
    paragraphs: [
      "Clone the repository, create a virtual environment, install the package, and launch installer.py as root for full transparency.",
      "This route is great when you want to tweak config defaults or audit every file before running."
    ],
    bullets: [
      "Product installs can create systemd services; the installer asks whether each service should start automatically at boot.",
      "Product directories live below /var/www/plex by default. Configuration filenames depend on the supplied product archive."
    ]
  },
  {
    title: "After installation",
    paragraphs: [
      "Use plex list to confirm running services.",
      "Create backups via Manage Backups (option 10 inside plexinstaller).",
      "Harden SSH and enable unattended-upgrades to keep the OS patched."
    ]
  }
];

export const faqSections: DocsSection[] = [
  {
    title: "Is this official?",
    paragraphs: ["No. PlexDev Installer is community-maintained and is not affiliated with or endorsed by PlexDevelopment."],
    bullets: ["Use this repository's issue tracker for installer bugs. Product or licensing support depends on the vendor's own policies and your entitlement."]
  },
  {
    title: "Does the installer include Plex products?",
    paragraphs: ["Never. You must provide the PlexDevelopment files, licenses, and API keys on your server before running the installer."],
    bullets: ["Upload archives to /opt/plexapps or specify another path during setup."]
  },
  {
    title: "How do updates work?",
    paragraphs: ["Interactive plexinstaller launches check the GitHub version manifest. If a newer version is available, you are prompted before managed installer files are replaced. Interactive plex CLI launches perform the same check; update-check failures are ignored."],
    bullets: ["Accepted updates verify release integrity and use a temporary rollback copy of installer files.", "The updater does not automatically back up deployed product data or promise uninterrupted services."]
  },
  {
    title: "Which OS versions are supported?",
    paragraphs: ["Ubuntu and Debian are the primary tested targets. Package-manager support exists for apt, dnf, yum, pacman, and zypper, while automatic MongoDB setup covers Debian/Ubuntu, RHEL-family/Fedora, and Arch paths. Exact releases outside the primary targets may fail as upstream repositories change."],
    bullets: ["Use a disposable host or backup first, and expect to install unsupported dependencies manually.", "Root access is required by the interactive installer."]
  }
];

export const termsSections: DocsSection[] = [
  {
    title: "Unofficial status",
    paragraphs: ["PlexDev Installer is not affiliated with PlexDevelopment. Using it does not grant licenses or support entitlements."],
    bullets: ["You must already own rights to the PlexDevelopment or Drako products you deploy."]
  },
  {
    title: "Use at your own risk",
    paragraphs: ["Scripts modify system packages, configure MongoDB, and create services. Review the code before executing on production hosts."],
    bullets: ["We are not responsible for downtime, data loss, or security issues resulting from this installer." ]
  },
  {
    title: "Acceptable use",
    paragraphs: ["Do not use PlexDev Installer to violate PlexDevelopment terms or redistribute their software."],
    bullets: ["Comply with all applicable laws, export controls, and hosting provider policies."]
  }
];

export const privacySections: DocsSection[] = [
  {
    title: "Installer telemetry",
    paragraphs: ["setup.sh itself does not send installer telemetry. On the first interactive plexinstaller launch, you are asked whether to enable diagnostics. If enabled, telemetry starts only when a product installation begins and is posted to https://plexdev.xyz/tel when that attempt finishes."],
    bullets: [
      "Payloads include a generated session ID, product and instance names, overall status, failure step and error text, timestamps, per-step status/details, and the generated installation log.",
      "Step details can include local archive and installation paths, selected domain and port, instance names, and error messages. The client redacts common MongoDB credentials, password/token/secret key-value patterns, and bearer tokens, but no redactor can guarantee removal of every sensitive value.",
      "Enabled logs are also written locally below /opt/plexinstaller/telemetry/logs. The server stores events, logs, and recent aggregate summaries in its telemetry/data directory.",
      "The server rotates event archives and prunes logs using configured age, count, and size limits. Exact retention depends on the server deployment.",
      "The telemetry client does not intentionally upload PlexDevelopment archives or application customer databases. Review logs before separately using any support-log upload feature."
    ]
  },
  {
    title: "Choice and controls",
    paragraphs: ["The initial telemetry prompt defaults to disabled if you press Enter or run without a terminal. The preference is stored in /etc/plex/telemetry_pref; explicitly choose yes to opt in, or write disabled to opt out before a later run. Disabling telemetry prevents new telemetry sessions and uploads."],
    bullets: ["Installer update checks and setup downloads still contact GitHub and plexdev.xyz independently of the telemetry preference.", "Deleting the local preference or log files does not delete data already received by the telemetry server."]
  },
  {
    title: "Website analytics and advertising",
    paragraphs: ["plexdev.xyz loads Google Analytics (measurement ID G-368VLJG2ZX) and Google AdSense (publisher ca-pub-7983111910687324). These services may process identifiers, cookie or local-storage data, IP/device/browser information, page interactions, and advertising data under Google's privacy terms and applicable law."],
    bullets: ["Google provides its own privacy and advertising controls. Browser privacy settings or content blockers may provide additional controls.", "Website analytics and advertising are separate from the installer's terminal telemetry preference."]
  },
  {
    title: "Access and deletion requests",
    paragraphs: ["Email privacy@plexdev.xyz with an approximate UTC timestamp, product, instance name, and session ID if available so a stored installer event can be located. Do not send passwords, license keys, archives, or unredacted logs by email."],
    bullets: ["Requests will be handled as reasonably possible and as required by applicable law; no fixed response or deletion time is promised here.", "Requests concerning Google data may also need to be directed to Google."]
  }
];
