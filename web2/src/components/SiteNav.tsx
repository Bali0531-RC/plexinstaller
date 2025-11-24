const links = [
  { href: "/#install", label: "Installer" },
  { href: "/#platform", label: "Platform" },
  { href: "/#changelog", label: "Changelog" },
  { href: "/guide.html", label: "Guide" },
  { href: "/faq.html", label: "FAQ" },
  { href: "/terms.html", label: "TOS" },
  { href: "/privacy.html", label: "Privacy" },
  { href: "/setup.sh", label: "setup.sh", download: true }
];

export const SiteNav = ({ sticky = false }: { sticky?: boolean }) => (
  <nav className={`site-nav${sticky ? " sticky" : ""}`}>
    <a className="logo" href="/">
      plexdev.live
    </a>
    <div className="nav-links">
      {links.map((link) => (
        <a key={link.label} href={link.href} {...(link.download ? { download: "setup.sh" } : {})}>
          {link.label}
        </a>
      ))}
    </div>
  </nav>
);
