export type Product = {
  name: string;
  description: string;
  port: number;
  family: "Plex Development" | "Drako Development";
};

export const products: Product[] = [
  { name: "PlexTickets", description: "Ticket bot with an optional web dashboard.", port: 3000, family: "Plex Development" },
  { name: "PlexStaff", description: "Discord staff and moderation management.", port: 3001, family: "Plex Development" },
  { name: "DrakoStatus", description: "Public status page and uptime history.", port: 3002, family: "Drako Development" },
  { name: "DrakoStore", description: "Digital products, license keys, and order management.", port: 3003, family: "Drako Development" },
  { name: "DrakoForms", description: "Self-hosted forms and intake workflows.", port: 3004, family: "Drako Development" },
  { name: "DrakoLinks", description: "Link directory and short-link management.", port: 3005, family: "Drako Development" },
  { name: "DrakoPaste", description: "Temporary and permanent paste sharing.", port: 3006, family: "Drako Development" },
  { name: "DrakoTracker", description: "Feature-request and bug tracking.", port: 3007, family: "Drako Development" }
];
