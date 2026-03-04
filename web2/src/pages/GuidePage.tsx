import { DocsLayout } from "../sections/DocsLayout";
import { guideSections } from "../data/docs";

export const GuidePage = () => (
  <DocsLayout
    title="Installation Guide"
    description="Step-by-step walkthrough for deploying PlexDevelopment products on your own hardware."
    sections={guideSections}
  />
);
