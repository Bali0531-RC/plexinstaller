import { useEffect, useState } from "react";
import type { KeyboardEvent } from "react";
import { CommandBlock } from "./components/CommandBlock";
import { ProductGrid } from "./components/ProductGrid";
import { ReleaseTimeline } from "./components/ReleaseTimeline";
import { SiteNav } from "./components/SiteNav";
import { installerContent, InstallerTab } from "./data/installers";
import { releases } from "./data/changelog";

const currentVersion = releases[0]?.version ?? "unknown";

const installerTabs: { id: InstallerTab; label: string }[] = [
  { id: "quick", label: "Quick install" },
  { id: "manual", label: "Manual" },
  { id: "update", label: "Updating" }
];

const setupSteps = [
  ["01", "System check", "Detects your distribution and required packages."],
  ["02", "Database", "Creates an isolated MongoDB database and credentials when required."],
  ["03", "Service", "Installs dependencies and creates an optional systemd service."],
  ["04", "Network", "Configures the selected port, firewall, domain, nginx, and TLS."],
  ["05", "Verification", "Runs service, database, port, and HTTP health checks."],
] as const;

export const App = () => {
  const [activeTab, setActiveTab] = useState<InstallerTab>("quick");
  const content = installerContent[activeTab];

  const selectTab = (index: number) => {
    const tab = installerTabs[index];
    setActiveTab(tab.id);
    requestAnimationFrame(() => document.getElementById(`tab-${tab.id}`)?.focus());
  };

  const handleTabKeyDown = (event: KeyboardEvent<HTMLButtonElement>, index: number) => {
    if (event.key === "ArrowRight") {
      event.preventDefault();
      selectTab((index + 1) % installerTabs.length);
    } else if (event.key === "ArrowLeft") {
      event.preventDefault();
      selectTab((index - 1 + installerTabs.length) % installerTabs.length);
    } else if (event.key === "Home" || event.key === "End") {
      event.preventDefault();
      selectTab(event.key === "Home" ? 0 : installerTabs.length - 1);
    }
  };

  useEffect(() => {
    if (window.location.hash) {
      const id = window.location.hash.slice(1);
      const el = document.getElementById(id);
      if (el) {
        requestAnimationFrame(() => requestAnimationFrame(() => el.scrollIntoView({ behavior: "smooth" })));
      }
    }
  }, []);

  return (
    <div className="page">
      <a className="skip-link" href="#main">Skip to content</a>
      <SiteNav />
      <main id="main">
        <header className="hero">
          <div className="release-badge">Stable release <strong>v{currentVersion}</strong></div>
          <h1>Install your licensed PlexDevelopment and Drako apps on Linux.</h1>
          <p className="hero-summary">
            Community-maintained automation for MongoDB, systemd, firewall rules, domains, TLS, and post-install checks. Tested primarily on Ubuntu and Debian.
          </p>
          <div className="actions">
            <a className="primary" href="#install">Install</a>
            <a className="secondary" href="/guide.html">Read the guide</a>
          </div>
          <dl className="trust-list">
            <div><dt>Signed</dt><dd>GPG-verified releases</dd></div>
            <div><dt>Open source</dt><dd>Review every system change</dd></div>
            <div><dt>Bring your own</dt><dd>Product files are not included</dd></div>
          </dl>
        </header>

      <section id="install" className="install">
        <div className="section-heading">
          <div>
            <p className="section-kicker">Get started</p>
            <h2>Install the management tool</h2>
            <p>The bootstrap verifies the signed release before replacing anything under <code>/opt/plexinstaller</code>.</p>
          </div>
          <div className="tabs" role="tablist" aria-label="Installation method">
            {installerTabs.map((tab, index) => (
              <button
                key={tab.id}
                id={`tab-${tab.id}`}
                role="tab"
                className={tab.id === activeTab ? "active" : ""}
                onClick={() => setActiveTab(tab.id)}
                onKeyDown={(event) => handleTabKeyDown(event, index)}
                aria-selected={tab.id === activeTab}
                aria-controls={`panel-${tab.id}`}
                tabIndex={tab.id === activeTab ? 0 : -1}
              >
                {tab.label}
              </button>
            ))}
          </div>
        </div>
        <div className="install-panel" role="tabpanel" id={`panel-${activeTab}`} aria-labelledby={`tab-${activeTab}`}>
          <h3>{content.title}</h3>
          <p>{content.description}</p>
          {content.command && <CommandBlock command={content.command} />}
          {content.steps && (
            <ol>
              {content.steps.map((step) => (
                <li key={step}><code>{step}</code></li>
              ))}
            </ol>
          )}
          {content.notes && (
            <ul className="notes">
              {content.notes.map((note) => (
                <li key={note}>{note}</li>
              ))}
            </ul>
          )}
          <div className="inline-links">
            <a href="https://github.com/Bali0531-RC/plexinstaller/blob/main/web2/public/setup.sh" target="_blank" rel="noreferrer">Review setup.sh</a>
            <a href="/guide.html">Installation guide</a>
          </div>
        </div>
      </section>

      <aside className="notice" aria-labelledby="license-title">
        <strong id="license-title">Have your product archive and license ready.</strong>
        <p>The installer does not distribute PlexDevelopment or Drako software.</p>
      </aside>

      <section id="configuration" className="configuration">
        <div className="section-heading">
          <div>
            <p className="section-kicker">Workflow</p>
            <h2>What it changes</h2>
          </div>
        </div>
        <ol className="setup-steps">
          {setupSteps.map(([number, title, description]) => (
            <li key={number}>
              <span>{number}</span>
              <div><h3>{title}</h3><p>{description}</p></div>
            </li>
          ))}
        </ol>
      </section>

      <section id="products">
        <div className="section-heading">
          <div>
            <p className="section-kicker">Compatibility</p>
            <h2>Supported products</h2>
            <p>New Drako installs use <code>drako*</code> names. Existing <code>plex*</code> installations continue to work.</p>
          </div>
        </div>
        <ProductGrid />
      </section>

      <div className="closing-grid">
        <section id="changelog">
          <div className="section-heading compact">
            <div><p className="section-kicker">Project</p><h2>Recent releases</h2></div>
          </div>
          <ReleaseTimeline />
        </section>
        <section className="resource-list" aria-labelledby="resources-title">
          <div className="section-heading compact">
            <div><p className="section-kicker">Resources</p><h2 id="resources-title">Useful links</h2></div>
          </div>
          <a href="https://github.com/Bali0531-RC/plexinstaller/issues" target="_blank" rel="noreferrer"><strong>Report an installer bug</strong><span>Include your OS and a redacted log.</span></a>
          <a href="https://addons.plexdev.xyz" target="_blank" rel="noreferrer"><strong>Addon registry</strong><span>Browse community extensions.</span></a>
          <a href="/faq.html"><strong>Common questions</strong><span>Support, compatibility, and updates.</span></a>
        </section>
      </div>
      </main>
      <footer>
        <span>Unofficial community project.</span>
        <nav aria-label="Footer navigation"><a href="/privacy.html">Privacy</a><a href="/terms.html">Terms</a><a href="mailto:bali0531@plexdev.xyz">Contact</a></nav>
      </footer>
    </div>
  );
};

export default App;
