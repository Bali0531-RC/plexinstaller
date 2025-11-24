import { ssoConnectors } from "../data/sso";

export const SsoGrid = () => (
  <div className="grid sso-grid">
    {ssoConnectors.map((connector) => (
      <div key={connector.name} className="card">
        <div className="card-header">
          <div>
            <p className="eyebrow">SSO Connector</p>
            <h3>{connector.name}</h3>
          </div>
        </div>
        <p>{connector.description}</p>
        <div className="pill-row">
          {connector.providers.map((provider) => (
            <span key={provider} className="pill">
              {provider}
            </span>
          ))}
        </div>
      </div>
    ))}
  </div>
);
