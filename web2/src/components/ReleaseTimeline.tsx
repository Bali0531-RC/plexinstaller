import { releases } from "../data/changelog";

export const ReleaseTimeline = () => (
  <div className="timeline">
    {releases.slice(0, 2).map((release) => (
      <article key={release.version} className="release-row">
        <header className="card-header">
          <div>
            <h3>v{release.version}</h3>
            <time dateTime={release.date}>{release.date}</time>
          </div>
        </header>
        <ul>
          {release.highlights.slice(0, 3).map((item) => (
            <li key={item}>{item}</li>
          ))}
        </ul>
      </article>
    ))}
    <a className="text-link" href="/changelog.html">
      View complete changelog
    </a>
  </div>
);
