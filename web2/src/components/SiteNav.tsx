import { Link, useLocation, useNavigate } from "react-router-dom";

type NavLink = {
  to: string;
  label: string;
  download?: boolean;
};

const links: NavLink[] = [
  { to: "/#install", label: "Installer" },
  { to: "/#platform", label: "Platform" },
  { to: "/#changelog", label: "Changelog" },
  { to: "/guide", label: "Guide" },
  { to: "/faq", label: "FAQ" },
  { to: "/terms", label: "TOS" },
  { to: "/privacy", label: "Privacy" },
  { to: "/setup.sh", label: "setup.sh", download: true },
];

export const SiteNav = ({ sticky = false }: { sticky?: boolean }) => {
  const location = useLocation();
  const navigate = useNavigate();

  const handleHashClick = (e: React.MouseEvent<HTMLAnchorElement>, to: string) => {
    e.preventDefault();
    const id = to.slice(2); // "/#install" -> "install"
    if (location.pathname === "/") {
      document.getElementById(id)?.scrollIntoView({ behavior: "smooth" });
    } else {
      navigate(to);
    }
  };

  return (
    <nav className={`site-nav${sticky ? " sticky" : ""}`}>
      <Link className="logo" to="/">
        plexdev.xyz
      </Link>
      <div className="nav-links">
        {links.map((link) => {
          const isHash = link.to.startsWith("/#");
          const isActive = !isHash && !link.download && location.pathname === link.to;

          if (link.download) {
            return (
              <a key={link.label} href={link.to} download>
                {link.label}
              </a>
            );
          }

          if (isHash) {
            return (
              <a key={link.label} href={link.to} onClick={(e) => handleHashClick(e, link.to)}>
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
        <a href="https://addons.plexdev.xyz" className="nav-addons" target="_blank" rel="noreferrer">
          🧩 Addons
        </a>
      </div>
    </nav>
  );
};
