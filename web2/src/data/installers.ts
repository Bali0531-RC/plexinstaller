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
    title: "Signed bootstrap",
    description: "Installs the verified management tool under /opt/plexinstaller. Product deployment starts only after you run plexinstaller.",
    command: "curl -fsSL https://plexdev.xyz/setup.sh | sudo bash",
    notes: [
      "Have your licensed product archive ready before opening the installer.",
      "The stable channel requires a valid release signature and matching checksums."
    ]
  },
  manual: {
    title: "Install from source",
    description: "Clone the repository and inspect the code before running it with root privileges.",
    steps: [
      "git clone https://github.com/Bali0531-RC/plexinstaller.git",
      "cd plexinstaller",
      "python3 -m venv .venv && source .venv/bin/activate",
      "python3 -m pip install -e .",
      "sudo .venv/bin/python installer.py"
    ],
    notes: [
      "Ubuntu and Debian are the primary tested targets.",
      "Review each prompt before allowing package, firewall, database, nginx, or service changes."
    ]
  },
  update: {
    title: "Signed updates",
    description: "The installer checks the signed GitHub release manifest and asks before replacing managed files.",
    notes: [
      "Accepted self-updates verify signatures/checksums and temporarily back up managed installer files for rollback; they do not back up deployed product data or configuration.",
      "Update-check failures do not block normal use. Re-running setup.sh re-downloads the bootstrap bundle."
    ]
  }
};
