import { DocsLayout } from "../sections/DocsLayout";
import { faqSections } from "../data/docs";

export const FaqPage = () => (
  <DocsLayout
    title="Frequently Asked Questions"
    description="Answers to the most common PlexDev Installer questions."
    sections={faqSections}
  />
);
