import { MouseEvent, useState } from "react";

export const CommandBlock = ({ command }: { command: string }) => {
  const [copied, setCopied] = useState(false);

  const handleCopy = async (event: MouseEvent<HTMLButtonElement>) => {
    event.preventDefault();
    try {
      await navigator.clipboard.writeText(command);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch (error) {
      console.error("Failed to copy command", error);
    }
  };

  return (
    <div className="command-block">
      <span className="prompt" aria-hidden="true">$</span>
      <code>{command}</code>
      <button onClick={handleCopy} aria-label="Copy install command">
        {copied ? "Copied" : "Copy"}
      </button>
      <span className="sr-only" aria-live="polite">{copied ? "Command copied to clipboard" : ""}</span>
    </div>
  );
};
