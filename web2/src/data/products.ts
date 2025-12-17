export type Product = {
  name: string;
  description: string;
  port: number;
  category: string;
};

export const products: Product[] = [
  { name: "PlexTickets", description: "Full-stack support ticket system with dashboard option.", port: 3000, category: "Support" },
  { name: "PlexStaff", description: "Discord-first moderation toolkit that replaces basic server mod flows.", port: 3001, category: "Operations" },
  { name: "PlexStatus", description: "Public-facing status page with uptime history for your stack.", port: 3002, category: "Monitoring" },
  { name: "PlexStore", description: "Direct digital goods and license key sales without extra webhook wiring.", port: 3003, category: "Commerce" },
  { name: "PlexForms", description: "Self-hosted form builder for intake flows and lightweight automation.", port: 3004, category: "Automation" },
  { name: "PlexLinks", description: "Link directory and short-link manager.", port: 3005, category: "Content" },
  { name: "PlexPaste", description: "Secure pastebin with temporary secrets.", port: 3006, category: "Utilities" },
  { name: "PlexTracker", description: "Tracking suggestions and bugs.", port: 3007, category: "Tracking" }
];
