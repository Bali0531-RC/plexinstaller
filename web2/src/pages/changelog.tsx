import React from "react";
import ReactDOM from "react-dom/client";
import { SiteNav } from "../components/SiteNav";
import { releases } from "../data/changelog";
import "../styles.css";

const releaseId = (version: string) => `v${version.replace(/[^a-zA-Z0-9.-]/g, "-")}`;

const ChangelogPage = () => (
  <div className="page docs-page">
    <a className="skip-link" href="#release-history">Skip to release history</a>
    <SiteNav />
    <main id="release-history" className="docs-shell">
      <header className="docs-hero">
        <p className="section-kicker">Project history</p>
        <h1>Changelog</h1>
        <p>Complete release history recorded by the installer project, including versions that predate GitHub Releases.</p>
      </header>
      <div className="changelog-layout">
        <aside className="toc release-index" aria-label="Release index">
          <strong>Versions</strong>
          {releases.map((release) => <a key={release.version} href={`#${releaseId(release.version)}`}>v{release.version}</a>)}
        </aside>
        <div className="release-history">
          {releases.map((release, index) => (
            <article key={release.version} id={releaseId(release.version)} className="release-entry">
              <header>
                <div>
                  <h2>v{release.version}</h2>
                  {index === 0 && <span className="current-release">Current</span>}
                </div>
                <time dateTime={release.date}>{release.date}</time>
              </header>
              <ul>
                {release.highlights.map((highlight) => <li key={highlight}>{highlight}</li>)}
              </ul>
            </article>
          ))}
        </div>
      </div>
    </main>
    <footer>
      <span>Unofficial community project.</span>
      <nav aria-label="Footer navigation"><a href="/privacy.html">Privacy</a><a href="/terms.html">Terms</a><a href="https://github.com/Bali0531-RC/plexinstaller">GitHub</a></nav>
    </footer>
  </div>
);

ReactDOM.createRoot(document.getElementById("root") as HTMLElement).render(
  <React.StrictMode><ChangelogPage /></React.StrictMode>
);
