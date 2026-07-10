import { ExternalLinkIcon } from "./icons";

type NavLink = {
  to: string;
  label: string;
  download?: boolean;
};

const links: NavLink[] = [
  { to: "/#install", label: "Install" },
  { to: "/#products", label: "Products" },
  { to: "/guide.html", label: "Guide" },
  { to: "/changelog.html", label: "Changelog" },
  { to: "/faq.html", label: "FAQ" },
];

export const SiteNav = ({ sticky = false }: { sticky?: boolean }) => {
  const pathname = window.location.pathname;

  return (
    <nav className={`site-nav${sticky ? " sticky" : ""}`} aria-label="Primary navigation">
      <a className="brand" href="/" aria-label="PlexDev Installer home">
        <span className="brand-mark" aria-hidden="true">P</span>
        <span>
          <strong>PlexDev Installer</strong>
          <small>Community project</small>
        </span>
      </a>
      <div className="nav-links">
        {links.map((link) => {
          const isHash = link.to.startsWith("/#");
          const isActive = !isHash && !link.download &&
            (pathname === link.to || pathname === link.to.replace(/\.html$/, ""));

          if (link.download) {
            return (
              <a key={link.label} href={link.to} download>
                {link.label}
              </a>
            );
          }

          if (isHash) {
            return (
              <a key={link.label} href={link.to}>
                {link.label}
              </a>
            );
          }

          return (
            <a key={link.label} href={link.to} className={isActive ? "active" : ""} aria-current={isActive ? "page" : undefined}>
              {link.label}
            </a>
          );
        })}
        <a href="https://github.com/Bali0531-RC/plexinstaller" className="nav-github" target="_blank" rel="noreferrer">
          GitHub
          <ExternalLinkIcon className="nav-external-icon" />
        </a>
      </div>
    </nav>
  );
};
