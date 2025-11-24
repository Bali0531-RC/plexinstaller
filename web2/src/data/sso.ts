export type SsoConnector = {
  name: string;
  description: string;
  providers: string[];
};

export const ssoConnectors: SsoConnector[] = [
  {
    name: "Discord OAuth2",
    description: "Native support for guild role syncing, vanity joins, and scoped bot tokens for PlexTickets and PlexStaff.",
    providers: ["Discord", "Plex SSO"]
  },
  {
    name: "Generic OIDC",
    description: "Use any standards-compliant OpenID Connect identity provider to handle staff access across dashboards.",
    providers: ["Keycloak", "Auth0", "Azure AD"]
  },
  {
    name: "SAML 2.0 Relay",
    description: "Map claims to Plex roles, perfect for enterprise deployments that need audit trails and enforced MFA.",
    providers: ["Okta", "Google Workspace", "JumpCloud"]
  }
];
