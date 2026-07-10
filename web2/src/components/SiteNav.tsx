import { useLocation } from "react-router-dom";
import { ExternalLinkIcon } from "./icons";

type NavLink = {
  to: string;
  label: string;
  download?: boolean;
};

const links: NavLink[] = [
  { to: "/#install", label: "Installer" },
  { to: "/#platform", label: "Platform" },
  { to: "/#changelog", label: "Changelog" },
  { to: "/guide.html", label: "Guide" },
  { to: "/faq.html", label: "FAQ" },
  { to: "/terms.html", label: "TOS" },
  { to: "/privacy.html", label: "Privacy" },
  { to: "/setup.sh", label: "setup.sh", download: true },
];

export const SiteNav = ({ sticky = false }: { sticky?: boolean }) => {
  const location = useLocation();

  return (
    <nav className={`site-nav${sticky ? " sticky" : ""}`}>
      <a className="logo" href="/">
        plexdev.xyz
      </a>
      <div className="nav-links">
        {links.map((link) => {
          const isHash = link.to.startsWith("/#");
          const isActive = !isHash && !link.download &&
            (location.pathname === link.to || location.pathname === link.to.replace(/\.html$/, ""));

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

          return <a key={link.label} href={link.to} className={isActive ? "active" : ""}>{link.label}</a>;
        })}
        <a href="https://addons.plexdev.xyz" className="nav-addons" target="_blank" rel="noreferrer">
          Addons
          <ExternalLinkIcon className="nav-external-icon" />
        </a>
      </div>
    </nav>
  );
};
