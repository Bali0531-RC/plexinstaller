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
    title: "Quick Install",
    description: "Best for clean Ubuntu 22.04+ hosts. Fetches the latest unofficial PlexDevelopment installer bundled with MongoDB 8.x helpers and hardening defaults.",
    command: "curl -sSL https://plexdev.live/setup.sh | sudo bash",
    notes: [
      "Append -b to opt into the beta channel: curl -sSL https://plexdev.live/setup.sh | sudo bash -s -- -b",
      "Script only prepares the tooling; you must upload PlexDevelopment product files yourself."
    ]
  },
  manual: {
    title: "Manual Install",
    description: "Prefer to inspect scripts first? Clone the repo and run the Python installer yourself.",
    steps: [
      "git clone https://github.com/Bali0531-RC/plexinstaller.git",
      "cd plexinstaller",
      "python3 -m venv .venv && source .venv/bin/activate",
      "pip install -r requirements.txt",
      "python installer.py"
    ],
    notes: [
      "Installer auto-detects OS details and selects proper MongoDB channel.",
      "All services are configured under systemd with sane defaults."
    ]
  },
  update: {
    title: "Auto Updates",
    description: "The installer self-updates against GitHub every time you launch it, so just run 'plexinstaller' locally when you need to make changes—no more rerunning curl.",
    notes: [
      "Backups of config files land in /opt/plexinstaller/backups before any change.",
      "Need to force refresh manually? curl -sSL https://plexdev.live/setup.sh | sudo bash simply re-downloads the launcher."
    ]
  }
};
