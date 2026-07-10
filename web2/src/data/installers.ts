export type InstallerTab = "quick" | "manual" | "update";

type InstallerContent = {
  title: string;
  description: string;
  command?: string;
  steps?: string[];
  notes?: string[];
};

export const installerContent: Record<InstallerTab, InstallerContent> = {
  quick: {
    title: "Bootstrap",
    description: "Downloads the installer bundle and Python dependencies into /opt/plexinstaller, verifies release metadata where possible, and creates the plexinstaller and plex commands. It does not deploy a PlexDevelopment or Drako product by itself.",
    command: "curl -fsSL https://plexdev.xyz/setup.sh | sudo bash",
    notes: [
      "Explicit beta mode: curl -fsSL https://plexdev.xyz/setup.sh | sudo bash -s -- --insecure-beta. This may bypass failed beta verification.",
      "At the end, setup.sh asks whether to launch the separate interactive installer; in a non-interactive session it defaults to no.",
      "You must provide licensed PlexDevelopment or Drako product archives yourself."
    ]
  },
  manual: {
    title: "Manual Install",
    description: "Prefer to inspect the code first? Clone the repository, install the package in a virtual environment, then run the interactive installer with root privileges.",
    steps: [
      "git clone https://github.com/Bali0531-RC/plexinstaller.git",
      "cd plexinstaller",
      "python3 -m venv .venv && source .venv/bin/activate",
      "python3 -m pip install -e .",
      "sudo .venv/bin/python installer.py"
    ],
    notes: [
      "Automatic system dependency and MongoDB setup varies by distribution; Ubuntu and Debian are the primary tested targets.",
      "Review prompts before allowing package, firewall, nginx, MongoDB, or systemd changes."
    ]
  },
  update: {
    title: "Update Checks",
    description: "Interactive plexinstaller launches check the GitHub release manifest. When a newer version exists, the installer displays the changelog and asks before replacing its managed files. Interactive plex CLI runs also check for updates.",
    notes: [
      "Accepted self-updates verify signatures/checksums and temporarily back up managed installer files for rollback; they do not back up deployed product data or configuration.",
      "Update-check failures do not block normal use. Re-running setup.sh re-downloads the bootstrap bundle."
    ]
  }
};
