import { DocsLayout } from "../sections/DocsLayout";
import { termsSections } from "../data/docs";

export const TermsPage = () => (
  <DocsLayout
    title="Terms of Use"
    description="Understand the boundaries and responsibilities when using the unofficial PlexDev Installer."
    sections={termsSections}
  />
);
