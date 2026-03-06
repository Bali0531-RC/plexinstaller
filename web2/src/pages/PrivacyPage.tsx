import { DocsLayout } from "../sections/DocsLayout";
import { privacySections } from "../data/docs";

export const PrivacyPage = () => (
  <DocsLayout
    title="Privacy"
    description="How plexdev.xyz handles telemetry, analytics, and data removal requests."
    sections={privacySections}
  />
);
