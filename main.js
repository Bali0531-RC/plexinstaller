// Main client-side script extracted from index.html
// This version avoids inline event handlers to work with strict CSP

// Set beta availability (server can replace this if templated)
const betaAvailable = true; // If needed, wire this from server

// Cached DOM references (initialized on DOMContentLoaded)
let versionToggle;
let betaUnavailableText;
let bodyElement;
let betaWarning;
let betaWarningTextElement;

// Array of random endings for the beta warning
const betaWarningEndings = [
  "Things might be wobbly!",
  "Expect some turbulence!",
  "Handle with care!",
  "May contain nuts... and bolts.",
  "Proceed with caution!",
  "It's alive... maybe?",
  "Don't feed after midnight.",
  "Under construction (literally)."
];
const baseBetaWarningText = "You've selected the Beta version. This version might have bugs or unfinished features. Use it at your own risk! ";

function switchTab(tabId) {
  const targetTabContent = document.getElementById(tabId);
  const targetTab = document.querySelector(`.tabs .tab[data-tab="${tabId}"]`);

  if (!targetTabContent || !targetTab) {
    console.error(`Tab or content not found for ID: ${tabId}`);
    return;
  }

  // Deactivate all
  document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
  document.querySelectorAll('.tabs .tab').forEach(tab => {
    tab.classList.remove('active');
    tab.setAttribute('aria-selected', 'false');
  });

  // Activate target
  targetTabContent.classList.add('active');
  targetTab.classList.add('active');
  targetTab.setAttribute('aria-selected', 'true');

  if (tabId === 'changelog') {
    showChangelogVersion('all');
  }
}

function copyFromButton(btn) {
  let text = '';
  const sel = btn.getAttribute('data-copy');
  if (sel) {
    const node = document.querySelector(sel);
    if (node) text = node.textContent;
  } else {
    // Fallback: previous sibling <code>
    const code = btn.previousElementSibling;
    if (code && code.tagName === 'CODE') text = code.textContent;
  }

  if (!text) return;

  navigator.clipboard.writeText(text).then(() => {
    const originalText = btn.textContent;
    btn.textContent = 'Copied!';
    btn.style.backgroundColor = 'var(--success)';
    setTimeout(() => {
      btn.textContent = originalText;
      btn.style.backgroundColor = '';
    }, 1500);
  }).catch(err => {
    console.error('Failed to copy text: ', err);
    alert('Failed to copy text.');
  });
}

function toggleVersion() {
  const isBeta = versionToggle && versionToggle.checked;
  const quickCode = document.getElementById('quick-install-code');
  const manualDownloadCode = document.getElementById('manual-download-code');
  const manualChmodCode = document.getElementById('manual-chmod-code');
  const manualRunCode = document.getElementById('manual-run-code');
  const stableLabel = document.getElementById('stable-label');
  const betaLabel = document.getElementById('beta-label');

  if (isBeta && betaAvailable) {
    bodyElement.classList.add('beta-theme');
    const randomIndex = Math.floor(Math.random() * betaWarningEndings.length);
    if (betaWarningTextElement) betaWarningTextElement.textContent = baseBetaWarningText + betaWarningEndings[randomIndex];
    if (betaWarning) betaWarning.style.display = 'block';

    if (quickCode) quickCode.textContent = 'curl -sSL https://plexdev.live/beta.sh | bash -i';
    if (manualDownloadCode) manualDownloadCode.textContent = 'curl -sSL -o beta.sh https://plexdev.live/beta.sh';
    if (manualChmodCode) manualChmodCode.textContent = 'chmod +x beta.sh';
    if (manualRunCode) manualRunCode.textContent = './beta.sh';
    if (stableLabel) stableLabel.style.opacity = '0.5';
    if (betaLabel) betaLabel.style.opacity = '1';
  } else {
    bodyElement.classList.remove('beta-theme');
    if (!betaAvailable && versionToggle) versionToggle.checked = false;
    if (betaWarning) betaWarning.style.display = 'none';

    if (quickCode) quickCode.textContent = 'curl -sSL https://plexdev.live/install.sh | bash -i';
    if (manualDownloadCode) manualDownloadCode.textContent = 'curl -sSL -o install.sh https://plexdev.live/install.sh';
    if (manualChmodCode) manualChmodCode.textContent = 'chmod +x install.sh';
    if (manualRunCode) manualRunCode.textContent = './install.sh';
    if (stableLabel) stableLabel.style.opacity = '1';
    if (betaLabel) betaLabel.style.opacity = betaAvailable ? '0.5' : '0.5';
  }
}

// Affiliate banner rotation
let currentPartnerIndex = 0;
let partnerRotationInterval = null;
const partners = ['partner-zap', 'partner-sparked'];
const rotationDelay = 5000; // 5 seconds

function rotatePartners() {
  const currentPartner = document.getElementById(partners[currentPartnerIndex]);
  const indicators = document.querySelectorAll('.affiliate-indicator');
  if (currentPartner) {
    currentPartner.classList.add('exit');
    setTimeout(() => {
      currentPartner.classList.remove('active', 'exit');
    }, 250);
  }
  indicators[currentPartnerIndex]?.classList.remove('active');

  currentPartnerIndex = (currentPartnerIndex + 1) % partners.length;
  setTimeout(() => {
    const nextPartner = document.getElementById(partners[currentPartnerIndex]);
    if (nextPartner) nextPartner.classList.add('active');
    indicators[currentPartnerIndex]?.classList.add('active');
  }, 250);
}

function startPartnerRotation() {
  setTimeout(() => {
    partnerRotationInterval = setInterval(rotatePartners, rotationDelay);
  }, rotationDelay);
}

function stopPartnerRotation() {
  if (partnerRotationInterval) {
    clearInterval(partnerRotationInterval);
    partnerRotationInterval = null;
  }
}

function showAffiliateBanner() {
  if (localStorage.getItem('affiliate-banner-closed') === 'true') return;
  const banner = document.getElementById('affiliate-banner');
  if (banner) {
    setTimeout(() => {
      banner.classList.add('show');
      startPartnerRotation();
    }, 2000);
  }
}

function closeAffiliateBanner() {
  const banner = document.getElementById('affiliate-banner');
  if (banner) {
    stopPartnerRotation();
    banner.classList.add('hide');
    localStorage.setItem('affiliate-banner-closed', 'true');
    setTimeout(() => banner.remove(), 300);
  }
}

// Changelog filter
function showChangelogVersion(version) {
  document.querySelectorAll('.changelog-tab').forEach(tab => tab.classList.remove('active'));
  const currentTab = document.querySelector(`.changelog-tab[data-version="${version}"]`);
  if (currentTab) currentTab.classList.add('active');

  const entries = document.querySelectorAll('.changelog-entry');
  entries.forEach(entry => {
    const entryVersion = entry.getAttribute('data-version');
    if (version === 'all' || entryVersion === version) {
      entry.classList.remove('hidden');
    } else {
      entry.classList.add('hidden');
    }
  });
}

// ZAP-Hosting coupon
function showZapCoupon(event) {
  const couponCode = 'bali0531-a-6918';
  const message = `🎉 ZAP-Hosting 20% Discount!\n\nCoupon Code: ${couponCode}\n\n✅ This code should auto-apply, but if not, use it manually at checkout!\n\nClick OK to continue to ZAP-Hosting...`;
  if (confirm(message)) {
    navigator.clipboard.writeText(couponCode).then(() => {
      const notification = document.createElement('div');
      notification.innerHTML = '📋 Coupon code copied to clipboard!';
      notification.style.cssText = `
        position: fixed; top: 20px; right: 20px;
        background: var(--success); color: white; padding: 12px 20px;
        border-radius: 8px; z-index: 10000; font-weight: 600;
        box-shadow: 0 4px 16px rgba(0, 0, 0, 0.3);
      `;
      document.body.appendChild(notification);
      setTimeout(() => notification.remove(), 3000);
    }).catch(err => console.error('Failed to copy coupon code:', err));
    return true;
  } else {
    event.preventDefault();
    return false;
  }
}

// Wire everything up after DOM is ready (defer ensures DOM is parsed)
document.addEventListener('DOMContentLoaded', () => {
  versionToggle = document.getElementById('version-toggle');
  betaUnavailableText = document.getElementById('beta-unavailable-text');
  bodyElement = document.body;
  betaWarning = document.getElementById('beta-warning');
  betaWarningTextElement = document.getElementById('beta-warning-text');

  // Initialize beta availability UI
  if (!betaAvailable && versionToggle) {
    versionToggle.disabled = true;
    if (betaUnavailableText) betaUnavailableText.style.display = 'inline';
  }

  // Labels toggle click handlers
  const stableLabel = document.getElementById('stable-label');
  const betaLabel = document.getElementById('beta-label');
  if (stableLabel && versionToggle) {
    stableLabel.addEventListener('click', () => { if (versionToggle.checked) versionToggle.click(); });
  }
  if (betaLabel && versionToggle) {
    betaLabel.addEventListener('click', () => { if (!versionToggle.checked) versionToggle.click(); });
  }

  // Tabs click (event delegation)
  const tabsBar = document.querySelector('.tabs');
  if (tabsBar) {
    tabsBar.addEventListener('click', (e) => {
      const tab = e.target.closest('.tab');
      if (!tab || !tabsBar.contains(tab)) return;
      const tabId = tab.getAttribute('data-tab');
      if (tabId) {
        e.preventDefault();
        switchTab(tabId);
      }
    });
  }

  // Copy buttons
  document.addEventListener('click', (e) => {
    const btn = e.target.closest('.copy-btn');
    if (btn) {
      e.preventDefault();
      copyFromButton(btn);
    }
  });

  // Version toggle change
  if (versionToggle) {
    versionToggle.addEventListener('change', toggleVersion);
  }

  // Affiliate banner close
  const closeBtn = document.getElementById('affiliate-close-btn');
  if (closeBtn) closeBtn.addEventListener('click', closeAffiliateBanner);

  // ZAP link coupon
  const zapLink = document.getElementById('zap-link');
  if (zapLink) zapLink.addEventListener('click', showZapCoupon);

  // Changelog tabs
  document.querySelectorAll('.changelog-tab').forEach(el => {
    el.addEventListener('click', () => {
      const v = el.getAttribute('data-version') || 'all';
      showChangelogVersion(v);
    });
  });

  // Initial state
  switchTab('quick');
  toggleVersion();
  showAffiliateBanner();
  setupPartnerIndicators();
});

function setupPartnerIndicators() {
  const indicators = document.querySelectorAll('.affiliate-indicator');
  indicators.forEach((indicator, index) => {
    indicator.addEventListener('click', () => {
      if (index === currentPartnerIndex) return;
      stopPartnerRotation();
      const currentPartner = document.getElementById(partners[currentPartnerIndex]);
      const targetPartner = document.getElementById(partners[index]);
      if (currentPartner) {
        currentPartner.classList.add('exit');
        setTimeout(() => currentPartner.classList.remove('active', 'exit'), 250);
      }
      document.querySelectorAll('.affiliate-indicator')[currentPartnerIndex]?.classList.remove('active');
      setTimeout(() => {
        if (targetPartner) targetPartner.classList.add('active');
        document.querySelectorAll('.affiliate-indicator')[index]?.classList.add('active');
        currentPartnerIndex = index;
      }, 250);
      setTimeout(() => startPartnerRotation(), 10000);
    });
  });
}

