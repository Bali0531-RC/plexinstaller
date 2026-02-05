import { useState } from "react";
import { CommandBlock } from "./components/CommandBlock";
import { ProductGrid } from "./components/ProductGrid";
import { ReleaseTimeline } from "./components/ReleaseTimeline";
import { SiteNav } from "./components/SiteNav";
import { installerContent, InstallerTab } from "./data/installers";

const installerTabs: { id: InstallerTab; label: string }[] = [
  { id: "quick", label: "Quick" },
  { id: "manual", label: "Manual" },
  { id: "update", label: "Update" }
];

export const App = () => {
  const [activeTab, setActiveTab] = useState<InstallerTab>("quick");
  const content = installerContent[activeTab];

  return (
    <div className="page">
      <div className="migration-banner">
        <span>🔄</span>
        <span>
          <strong>Domain Migration:</strong> We've moved from plexdev.live to plexdev.xyz! 
          Update your bookmarks. The old domain will redirect here until it expires (~60 days).
        </span>
      </div>
      <SiteNav />
      <main>
        <header className="hero">
        <p className="eyebrow">PlexDev Installer · v3.1.13</p>
        <h1>Unofficial PlexDevelopment installer for Linux hosts</h1>
        <p>
          plexdev.xyz is the home of the community-maintained installer. Bring your own PlexDevelopment product files and this script will handle MongoDB 8.x, systemd units, firewall rules, and health checks for you.
        </p>
        <div className="actions">
          <a className="primary" href="/setup.sh" download>
            Download setup.sh
          </a>
          <a className="ghost" href="/guide.html" target="_blank" rel="noreferrer">
            Read the guide
          </a>
          <a className="ghost" href="https://github.com/Bali0531-RC/plexinstaller" target="_blank" rel="noreferrer">
            View on GitHub
          </a>
        </div>
      </header>

      <section id="install" className="install">
        <div className="section-heading">
          <div>
            <p className="eyebrow">Installer</p>
            <h2>{content.title}</h2>
          </div>
          <div className="tabs" role="tablist">
            {installerTabs.map((tab) => (
              <button
                key={tab.id}
                role="tab"
                className={tab.id === activeTab ? "active" : ""}
                onClick={() => setActiveTab(tab.id)}
                aria-selected={tab.id === activeTab}
              >
                {tab.label}
              </button>
            ))}
          </div>
        </div>
        <div className="card">
          <p>{content.description}</p>
          {content.command && <CommandBlock command={content.command} />}
          {content.steps && (
            <ol>
              {content.steps.map((step) => (
                <li key={step}>{step}</li>
              ))}
            </ol>
          )}
          {content.notes && (
            <div className="notes">
              {content.notes.map((note) => (
                <p key={note}>• {note}</p>
              ))}
            </div>
          )}
        </div>
      </section>

      <section className="card notice">
        <p className="eyebrow">Friendly reminder</p>
        <p>
          This installer does not ship or license any PlexDevelopment products. Server owners must supply their own application files, keys, and content before running deployments.
        </p>
        <p>
          PlexDev Installer is a community-built helper on top of PlexDevelopment's self-hosting workflow. Treat this as an acceleration tool—official support still comes directly from PlexDevelopment once you deploy their products.
        </p>
      </section>

      <section id="platform">
        <div className="section-heading">
          <div>
            <p className="eyebrow">Platform</p>
            <h2>What the installer configures</h2>
          </div>
          <p className="hint">Ports and services are auto-configured but still easy to override.</p>
        </div>
        <ProductGrid />
      </section>

      <section id="changelog">
        <div className="section-heading">
          <div>
            <p className="eyebrow">Changelog</p>
            <h2>Always forward</h2>
          </div>
          <p className="hint">Full release notes live in the repo if you need deeper detail.</p>
        </div>
        <ReleaseTimeline />
      </section>

      <section id="addons" className="addons-promo card">
        <div className="addons-promo-content">
          <p className="eyebrow">New Platform</p>
          <h2>🧩 PlexDev Addons</h2>
          <p>
            Discover and share community-built addons for PlexDevelopment products. 
            Version checking, automatic updates, and a growing library of extensions.
          </p>
          <div className="actions">
            <a className="primary" href="https://addons.plexdev.xyz" target="_blank" rel="noreferrer">
              Explore Addons
            </a>
            <a className="ghost" href="https://addons.plexdev.xyz/docs" target="_blank" rel="noreferrer">
              Developer Docs
            </a>
          </div>
        </div>
        <div className="addons-promo-features">
          <div className="addons-feature">
            <span className="addons-feature-icon">📦</span>
            <span>Addon Registry</span>
          </div>
          <div className="addons-feature">
            <span className="addons-feature-icon">🔄</span>
            <span>Auto Updates</span>
          </div>
          <div className="addons-feature">
            <span className="addons-feature-icon">🔐</span>
            <span>Discord Auth</span>
          </div>
        </div>
      </section>

      <section id="support" className="cta card">
        <p className="eyebrow">Fast help</p>
        <h2>Need support?</h2>
        <p>
          SSH access or logs ready? Email the maintainer or open a GitHub issue and we will get your environment unblocked.
        </p>
        <div className="actions">
          <a className="primary" href="mailto:bali0531@plexdev.xyz">Email support</a>
          <a className="ghost" href="https://github.com/Bali0531-RC/plexinstaller/issues" target="_blank" rel="noreferrer">
            GitHub issues
          </a>
        </div>
      </section>
      </main>
    </div>
  );
};

export default App;
