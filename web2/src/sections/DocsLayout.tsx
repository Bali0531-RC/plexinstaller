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

export const DocsLayout = ({ title, description, sections }: DocsLayoutProps) => (
  <div className="page docs-page">
    <SiteNav />
    <header className="hero docs-hero">
      <p className="eyebrow">plexdev.xyz</p>
      <h1>{title}</h1>
      <p>{description}</p>
    </header>
    <div className="docs-sections">
      {sections.map((section) => (
        <section key={section.title} className="card docs-section">
          <h2>{section.title}</h2>
          {section.paragraphs.map((paragraph) => (
            <p key={paragraph}>{paragraph}</p>
          ))}
          {section.bullets && (
            <ul>
              {section.bullets.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          )}
        </section>
      ))}
    </div>
  </div>
);
