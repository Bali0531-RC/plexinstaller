import { SiteNav } from "../components/SiteNav";

export type DocsSection = {
  title: string;
  paragraphs: string[];
  bullets?: string[];
};

export type DocsLayoutProps = {
  title: string;
  description: string;
  sections: DocsSection[];
};

const sectionId = (title: string) => title.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");

export const DocsLayout = ({ title, description, sections }: DocsLayoutProps) => (
  <div className="page docs-page">
    <a className="skip-link" href="#article">Skip to content</a>
    <SiteNav />
    <main id="article" className="docs-shell">
      <header className="docs-hero">
        <p className="section-kicker">Documentation</p>
        <h1>{title}</h1>
        <p>{description}</p>
      </header>
      <div className="docs-layout">
        <aside className="toc" aria-label="On this page">
          <strong>On this page</strong>
          {sections.map((section) => <a key={section.title} href={`#${sectionId(section.title)}`}>{section.title}</a>)}
        </aside>
        <article className="docs-sections">
          {sections.map((section) => (
            <section key={section.title} id={sectionId(section.title)} className="docs-section">
              <h2>{section.title}</h2>
              {section.paragraphs.map((paragraph) => <p key={paragraph}>{paragraph}</p>)}
              {section.bullets && <ul>{section.bullets.map((item) => <li key={item}>{item}</li>)}</ul>}
            </section>
          ))}
        </article>
      </div>
    </main>
    <footer>
      <span>Unofficial community project.</span>
      <nav aria-label="Footer navigation"><a href="/privacy.html">Privacy</a><a href="/terms.html">Terms</a><a href="https://github.com/Bali0531-RC/plexinstaller">GitHub</a></nav>
    </footer>
  </div>
);
