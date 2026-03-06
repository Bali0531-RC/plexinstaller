import { Link, useLocation } from "react-router-dom";

const links = [
  { to: "/#install", label: "Installer" },
  { to: "/#platform", label: "Platform" },
  { to: "/#changelog", label: "Changelog" },
  { to: "/guide", label: "Guide" },
  { to: "/faq", label: "FAQ" },
  { to: "/terms", label: "TOS" },
  { to: "/privacy", label: "Privacy" },
];

export const SiteNav = ({ sticky = false }: { sticky?: boolean }) => {
  const location = useLocation();

  return (
    <nav className={`site-nav${sticky ? " sticky" : ""}`}>
      <Link className="logo" to="/">
        plexdev.xyz
      </Link>
      <div className="nav-links">
        {links.map((link) => {
          const isHash = link.to.startsWith("/#");
          const isActive = !isHash && location.pathname === link.to;

          if (isHash) {
            return (
              <a key={link.label} href={link.to}>
                {link.label}
              </a>
            );
          }

          return (
            <Link key={link.label} to={link.to} className={isActive ? "active" : ""}>
              {link.label}
            </Link>
          );
        })}
        <a href="/setup.sh" download="setup.sh">
          setup.sh
        </a>
        <a href="https://addons.plexdev.xyz" className="nav-addons" target="_blank" rel="noreferrer">
          🧩 Addons
        </a>
      </div>
    </nav>
  );
};
