import { useState, useEffect } from "react";
import { useLocation } from "react-router-dom";
import { CommandBlock } from "./components/CommandBlock";
import { ProductGrid } from "./components/ProductGrid";
import { ReleaseTimeline } from "./components/ReleaseTimeline";
import { SiteNav } from "./components/SiteNav";
import { RefreshIcon, PackageIcon, ShieldCheckIcon } from "./components/icons";
import { installerContent, InstallerTab } from "./data/installers";
import { releases } from "./data/changelog";

const currentVersion = releases[0]?.version ?? "unknown";

const installerTabs: { id: InstallerTab; label: string }[] = [
  { id: "quick", label: "Quick" },
  { id: "manual", label: "Manual" },
  { id: "update", label: "Update" }
];

export const App = () => {
  const [activeTab, setActiveTab] = useState<InstallerTab>("quick");
  const content = installerContent[activeTab];
  const location = useLocation();

  useEffect(() => {
    if (location.hash) {
      const id = location.hash.slice(1);
      const el = document.getElementById(id);
      if (el) {
        requestAnimationFrame(() => requestAnimationFrame(() => el.scrollIntoView({ behavior: "smooth" })));
      }
    }
  }, [location.hash]);

  return (
    <div className="page">
      <SiteNav />
      <main>
        <header className="hero">
        <p className="eyebrow">PlexDev Installer · v{currentVersion}</p>
        <h1>Unofficial PlexDevelopment and Drako installer for Linux hosts</h1>
        <p>
          Bring your own PlexTickets, PlexStaff, or Drako product files and this community installer will handle MongoDB 8.x, systemd units, firewall rules, and health checks for you.
        </p>
        <div className="actions">
          <a className="primary" href="/setup.sh" download>
            Download setup.sh
          </a>
          <a className="ghost" href="https://github.com/Bali0531-RC/plexinstaller" target="_blank" rel="noreferrer">
            View on GitHub
          </a>
          <a className="ghost" href="/guide.html">
            Read the guide
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
        <p className="eyebrow">Licensing</p>
        <p>
          This installer does not ship or license PlexDevelopment or Drako products. Server owners must supply their own application files, keys, and content before deployment.
        </p>
        <p>
          PlexDev Installer is a community-built helper and is not affiliated with PlexDevelopment. Use this project's GitHub issues for installer problems and the product vendor's own channels for product or licensing questions, subject to your entitlement.
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
            <h2>Recent releases</h2>
          </div>
          <p className="hint">Full release notes live in the repo if you need deeper detail.</p>
        </div>
        <ReleaseTimeline />
      </section>

      <section id="addons" className="addons-promo card">
        <div className="addons-promo-content">
          <p className="eyebrow">New Platform</p>
          <h2>PlexDev Addons</h2>
          <p>
            Discover and share community-built addons for supported products.
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
            <PackageIcon className="addons-feature-icon" />
            <span>Addon Registry</span>
          </div>
          <div className="addons-feature">
            <RefreshIcon className="addons-feature-icon" />
            <span>Auto Updates</span>
          </div>
          <div className="addons-feature">
            <ShieldCheckIcon className="addons-feature-icon" />
            <span>Discord Auth</span>
          </div>
        </div>
      </section>

      <section id="support" className="cta card">
        <p className="eyebrow">Support</p>
        <h2>Need support?</h2>
        <p>
          For installer bugs, include redacted logs and environment details in a GitHub issue. Email is also available, but support is best-effort and no response time or resolution is guaranteed.
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
