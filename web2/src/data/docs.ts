import { DocsSection } from "../sections/DocsLayout";

export const guideSections: DocsSection[] = [
  {
    title: "Before you start",
    paragraphs: [
      "Target a clean Ubuntu 22.04 or Debian 12 host with sudo access and at least 2 vCPU / 4 GB RAM.",
      "Upload the PlexDevelopment product archives you own to /opt/plexapps or any path you prefer—the installer never bundles them for you."
    ],
    bullets: [
      "Ensure ports 3000-3010 are open if you want the defaults.",
      "Point your domain’s DNS records before enabling HTTPS inside products.",
      "Keep the PlexDevelopment archives and license keys you own staged before launching the installer."
    ]
  },
  {
    title: "One-line quick install",
    paragraphs: [
      "Run curl -sSL https://plexdev.live/setup.sh | sudo bash and follow the prompts. The script fetches the latest Python installer, prepares MongoDB 8.x, and creates systemd units.",
      "When the script finishes, run plexinstaller to choose which PlexDevelopment products to configure." 
    ],
    bullets: [
      "Use -b for the beta channel if you want nightly fixes.",
      "Re-run plexinstaller any time—auto updates land before the UI loads."
    ]
  },
  {
    title: "Manual install flow",
    paragraphs: [
      "Clone the repository, create a virtual environment, install requirements, and launch python installer.py for full transparency.",
      "This route is great when you want to tweak config defaults or audit every file before running."
    ],
    bullets: [
      "All services are written to systemd so you can manage them with systemctl.",
      "Configs live in /var/www/plex/<app>/config.yml for easy editing."
    ]
  },
  {
    title: "After installation",
    paragraphs: [
      "Use plex list to confirm running services.",
      "Create backups via Manage Backups (option 9 inside plexinstaller).",
      "Harden SSH and enable unattended-upgrades to keep the OS patched."
    ]
  }
];

export const faqSections: DocsSection[] = [
  {
    title: "Is this official?",
    paragraphs: ["PlexDev Installer is community-maintained, but PlexDevelopment fully supports self-hosting when you follow their licensing and documentation."],
    bullets: ["Open tickets with PlexDevelopment for product-level issues; use this tool only to speed up server prep."]
  },
  {
    title: "Does the installer include Plex products?",
    paragraphs: ["Never. You must provide the PlexDevelopment files, licenses, and API keys on your server before running the installer."],
    bullets: ["Upload archives to /opt/plexapps or specify another path during setup."]
  },
  {
    title: "How do updates work?",
    paragraphs: ["Every plexinstaller run checks GitHub for the latest version and updates itself before touching your services."],
    bullets: ["Services stay online while binaries refresh.", "Backups are created automatically."]
  },
  {
    title: "Which OS versions are supported?",
    paragraphs: ["Ubuntu 22.04/24.04 LTS and Debian 12 are the primary targets. Other distros may work but are not tested."],
    bullets: ["You need root or sudo access to install dependencies."]
  }
];

export const termsSections: DocsSection[] = [
  {
    title: "Unofficial status",
    paragraphs: ["PlexDev Installer is not affiliated with PlexDevelopment. Using it does not grant licenses or support entitlements."],
    bullets: ["You must already own rights to the PlexDevelopment products you deploy."]
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
    title: "What we log",
    paragraphs: ["When you run setup.sh we log anonymized metrics such as installer version, distro, and success/failure codes to understand adoption."],
    bullets: ["No PlexDevelopment files or customer data leave your server."]
  },
  {
    title: "Third-party services",
    paragraphs: ["The website uses basic analytics (Plausible) to track page views without storing personal information."],
    bullets: ["If you enable Discord webhooks or email tests inside the installer, credentials stay on your host."]
  },
  {
    title: "Contact",
    paragraphs: ["Need data removed? Email privacy@plexdev.live and include timestamps plus any relevant metadata."],
    bullets: ["We respond within 7 days."]
  }
];
