import { releases } from "../data/changelog";

export const ReleaseTimeline = () => (
  <div className="timeline">
    {releases.map((release) => (
      <article key={release.version} className="card">
        <header className="card-header">
          <div>
            <p className="eyebrow">Released {release.date}</p>
            <h3>v{release.version}</h3>
          </div>
        </header>
        <ul>
          {release.highlights.map((item) => (
            <li key={item}>{item}</li>
          ))}
        </ul>
      </article>
    ))}
  </div>
);
