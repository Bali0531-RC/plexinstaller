export type Product = {
  name: string;
  description: string;
  port: number;
  category: string;
};

export const products: Product[] = [
  { name: "PlexTickets", description: "Full-stack support ticket system with dashboard option.", port: 3000, category: "Support" },
  { name: "PlexStaff", description: "Role-aware staff portal for internal teams.", port: 3001, category: "Operations" },
  { name: "PlexStatus", description: "Beautiful public status pages with incident tracking.", port: 3002, category: "Monitoring" },
  { name: "PlexStore", description: "Digital storefront with webhook-driven fulfillment.", port: 3003, category: "Commerce" },
  { name: "PlexForms", description: "Form builder with sane defaults and export tools.", port: 3004, category: "Automation" },
  { name: "PlexLinks", description: "Link directory and short-link manager.", port: 3005, category: "Content" },
  { name: "PlexPaste", description: "Secure pastebin with temporary secrets.", port: 3006, category: "Utilities" }
];
