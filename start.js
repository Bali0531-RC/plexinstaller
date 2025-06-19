const express = require('express');
const fs = require('fs');
const path = require('path');
const app = express();
const port = process.env.PORT || 31234;

// --- Helper Function to Read Files ---
function readFileSafe(filePath) {
  try {
    if (fs.existsSync(filePath)) {
      return fs.readFileSync(filePath, 'utf8');
    }
    return null; // Return null if file doesn't exist
  } catch (err) {
    console.error(`Error reading file ${filePath}:`, err);
    return null; // Return null on read error
  }
}

// --- Check if Beta Script Exists ---
const betaScriptPath = path.join(__dirname, 'beta.sh');
const betaScriptExists = fs.existsSync(betaScriptPath);

// --- Main Homepage Route ---
app.get('/', (req, res) => {
  res.send(`
    <!DOCTYPE html>
    <html>
    <head>
        <title>PlexDev.live - Unofficial Installer</title>
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <style>
            /* --- Basic Styles (Keep existing styles) --- */
            :root {
                --bg-primary: #121212;
                --bg-secondary: #1e1e1e;
                --text-primary: #e4e4e4;
                --text-secondary: #a0a0a0;
                --accent: #3498db;
                --accent-dark: #2980b9;
                --success: #2ecc71;
                --warning: #f39c12;
                --danger: #e74c3c;
                --card-bg: #252525;
                --border-color: #333;
            }
            * { box-sizing: border-box; margin: 0; padding: 0; }
            body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; line-height: 1.6; color: var(--text-primary); background-color: var(--bg-primary); max-width: 900px; margin: 0 auto; padding: 20px; transition: all 0.3s ease; }
            h1, h2, h3 { color: var(--text-primary); margin: 1.5rem 0 1rem 0; }
            h1 { font-size: 2.5rem; border-bottom: 2px solid var(--accent); padding-bottom: 10px; margin-bottom: 1.5rem; position: relative; }
            h1::after { content: ""; position: absolute; bottom: -2px; left: 0; width: 120px; height: 2px; background-color: var(--accent); animation: pulse 2s infinite; }
            h2 { font-size: 1.8rem; margin-top: 2rem; }
            p { margin: 1rem 0; color: var(--text-secondary); }
            a { color: var(--accent); text-decoration: none; transition: color 0.3s ease; }
            a:hover { color: var(--accent-dark); text-decoration: underline; }
            .code-block { background-color: var(--bg-secondary); border: 1px solid var(--border-color); border-radius: 6px; padding: 20px; margin: 20px 0; font-family: 'Consolas', 'Courier New', monospace; overflow-x: auto; position: relative; box-shadow: 0 4px 8px rgba(0,0,0,0.2); transition: all 0.3s ease; }
            .code-block:hover { box-shadow: 0 8px 16px rgba(0,0,0,0.3); transform: translateY(-2px); border-color: var(--accent); }
            .code-block code { color: #f1c40f; }
            .code-block::before { content: "$ "; opacity: 0.5; }
            .code-block .copy-btn { position: absolute; top: 10px; right: 10px; background: var(--accent); color: white; border: none; border-radius: 4px; padding: 5px 10px; cursor: pointer; font-size: 0.8rem; opacity: 0; transition: all 0.3s ease; }
            .code-block:hover .copy-btn { opacity: 1; }
            .code-block .copy-btn:hover { background: var(--accent-dark); }
            .card { background-color: var(--card-bg); border-radius: 8px; padding: 20px; margin: 20px 0; box-shadow: 0 4px 8px rgba(0,0,0,0.2); transition: all 0.3s ease; border-left: 4px solid var(--accent); }
            .card:hover { box-shadow: 0 8px 16px rgba(0,0,0,0.3); transform: translateY(-2px); }
            .warning { background-color: rgba(243, 156, 18, 0.1); border-left: 4px solid var(--warning); padding: 15px; margin: 20px 0; border-radius: 4px; }
            .official-note { background-color: rgba(52, 152, 219, 0.1); border-left: 4px solid var(--accent); padding: 15px; margin: 20px 0; border-radius: 4px; }
            footer { margin-top: 40px; color: var(--text-secondary); text-align: center; border-top: 1px solid var(--border-color); padding-top: 20px; font-size: 0.9rem; }
            .tabs { display: flex; margin: 20px 0; border-bottom: 1px solid var(--border-color); }
            .tab { padding: 10px 20px; cursor: pointer; color: var(--text-secondary); transition: all 0.3s ease; border-bottom: 2px solid transparent; }
            .tab.active { color: var(--accent); border-bottom: 2px solid var(--accent); }
            .tab-content { display: none; }
            .tab-content.active { display: block; animation: fadeIn 0.5s; }
            @keyframes pulse { 0% { opacity: 0.6; } 50% { opacity: 1; } 100% { opacity: 0.6; } }
            @keyframes fadeIn { from { opacity: 0; transform: translateY(10px); } to { opacity: 1; transform: translateY(0); } }
            @media (max-width: 768px) { body { padding: 15px; } h1 { font-size: 2rem; } .tabs { flex-direction: column; } }

            /* --- Toggle Switch Styles --- */
            .switch-container { display: flex; align-items: center; margin: 20px 0; background-color: var(--bg-secondary); padding: 10px 15px; border-radius: 6px; border: 1px solid var(--border-color); }
            .switch-container label { margin-right: 15px; color: var(--text-secondary); font-weight: bold; }
            .switch { position: relative; display: inline-block; width: 60px; height: 34px; }
            .switch input { opacity: 0; width: 0; height: 0; }
            .slider { position: absolute; cursor: pointer; top: 0; left: 0; right: 0; bottom: 0; background-color: #ccc; transition: .4s; border-radius: 34px; }
            .slider:before { position: absolute; content: ""; height: 26px; width: 26px; left: 4px; bottom: 4px; background-color: white; transition: .4s; border-radius: 50%; }
            input:checked + .slider { background-color: var(--accent); }
            input:focus + .slider { box-shadow: 0 0 1px var(--accent); }
            input:checked + .slider:before { transform: translateX(26px); }
            .switch-text { margin-left: 10px; font-weight: bold; }
            .stable-text { color: var(--success); }
            .beta-text { color: var(--warning); }
            #beta-warning { display: none; /* Hidden by default */ }
        </style>
    </head>
    <body>
        <h1>PlexDev.live Unofficial Installer</h1>
        <div class="official-note">
            <strong>⚠️ Important:</strong> This is an unofficial installer. The official PlexDevelopment website is
            <a href="https://plexdevelopment.net" target="_blank">plexdevelopment.net</a>. Need help understanding how this works? Check out the <a href="/guide">Simple Guide</a>!
        </div>

        <p>Welcome! This tool helps you easily set up various Plex products on your Linux server.</p>

        <!-- Version Toggle -->
        <div class="switch-container">
            <label for="version-toggle">Installation Mode:</label>
            <span class="switch-text stable-text" id="stable-label">Stable</span>
            <label class="switch">
                <input type="checkbox" id="version-toggle" ${!betaScriptExists ? 'disabled' : ''} onchange="toggleVersion()">
                <span class="slider"></span>
            </label>
            <span class="switch-text beta-text" id="beta-label">Beta</span>
            ${!betaScriptExists ? '<span style="margin-left: 15px; color: var(--danger);">(Beta script not available)</span>' : ''}
        </div>

        <!-- Beta Warning Message -->
        <div class="warning" id="beta-warning">
            <strong>Heads Up!</strong> You've selected the Beta version. This version might have bugs or unfinished features. Use it at your own risk!
        </div>

        <!-- Tabs -->
        <div class="tabs">
            <div class="tab active" onclick="switchTab('quick')">Quick Install</div>
            <div class="tab" onclick="switchTab('manual')">Manual Install</div>
            <div class="tab" onclick="switchTab('about')">About</div>
        </div>

        <!-- Quick Install Tab -->
        <div id="quick" class="tab-content active">
            <h2>Quick Installation</h2>
            <p>Copy and paste this command into your server's terminal. It downloads and runs the installer script automatically.</p>
            <div class="code-block" id="quick-install-block">
                <code id="quick-install-code">curl -sSL https://plexdev.live/install.sh | bash -i</code>
                <button class="copy-btn" onclick="copyToClipboard(document.getElementById('quick-install-code').textContent)">Copy</button>
            </div>
        </div>

        <!-- Manual Install Tab -->
        <div id="manual" class="tab-content">
            <h2>Manual Installation</h2>
            <p>If you prefer, download the script first, make it runnable, and then execute it.</p>

            <div id="manual-steps">
                <p><strong>Step 1: Download</strong></p>
                <div class="code-block">
                    <code id="manual-download-code">curl -sSL -o install.sh https://plexdev.live/install.sh</code>
                    <button class="copy-btn" onclick="copyToClipboard(document.getElementById('manual-download-code').textContent)">Copy</button>
                </div>

                <p><strong>Step 2: Make it Executable</strong></p>
                <div class="code-block">
                    <code id="manual-chmod-code">chmod +x install.sh</code>
                    <button class="copy-btn" onclick="copyToClipboard(document.getElementById('manual-chmod-code').textContent)">Copy</button>
                </div>

                <p><strong>Step 3: Run It</strong></p>
                <div class="code-block">
                    <code id="manual-run-code">./install.sh</code>
                    <button class="copy-btn" onclick="copyToClipboard(document.getElementById('manual-run-code').textContent)">Copy</button>
                </div>
            </div>
        </div>

        <!-- About Tab -->
        <div id="about" class="tab-content">
            <h2>About This Project</h2>
            <div class="card">
                <p>This project was created by <strong>bali0531</strong> to simplify the setup process for PlexDevelopment products.</p>
                <p>The installer automatically:</p>
                <ul style="margin-left: 20px; color: var(--text-secondary);">
                    <li>Detects your Linux distribution</li>
                    <li>Installs all necessary dependencies (like Node.js, Nginx)</li>
                    <li>Sets up Nginx web server configuration</li>
                    <li>Configures free SSL certificates (HTTPS) using Let's Encrypt</li>
                    <li>Creates systemd services to keep the products running</li>
                </ul>
            </div>
            <div class="warning">
                <strong>Disclaimer:</strong> This is an unofficial tool and is not officially supported by PlexDevelopment. Use at your own discretion.
            </div>
        </div>

        <footer>
            PlexDev.live made by: bali0531 | <a href="https://plexdevelopment.net" target="_blank">Official Site</a> | <a href="/guide">Simple Guide</a>
        </footer>

        <script>
            const betaAvailable = ${betaScriptExists}; // Pass server-side check to client

            function switchTab(tabId) {
                document.querySelectorAll('.tab-content').forEach(content => content.classList.remove('active'));
                document.querySelectorAll('.tab').forEach(tab => tab.classList.remove('active'));
                document.getElementById(tabId).classList.add('active');
                document.querySelector('.tab[onclick="switchTab(\'' + tabId + '\')"]').classList.add('active');
            }

            function copyToClipboard(text) {
                navigator.clipboard.writeText(text).then(() => {
                    const btn = event.target;
                    const originalText = btn.textContent;
                    btn.textContent = "Copied!";
                    setTimeout(() => { btn.textContent = originalText; }, 2000);
                }).catch(err => {
                    console.error('Failed to copy text: ', err);
                    // Fallback for older browsers (less reliable)
                    try {
                        const el = document.createElement('textarea');
                        el.value = text;
                        document.body.appendChild(el);
                        el.select();
                        document.execCommand('copy');
                        document.body.removeChild(el);
                        const btn = event.target;
                        const originalText = btn.textContent;
                        btn.textContent = "Copied!";
                        setTimeout(() => { btn.textContent = originalText; }, 2000);
                    } catch (fallbackErr) {
                        alert('Failed to copy text.');
                    }
                });
            }

            function toggleVersion() {
                const isBeta = document.getElementById('version-toggle').checked;
                const betaWarning = document.getElementById('beta-warning');
                const quickCode = document.getElementById('quick-install-code');
                const manualDownloadCode = document.getElementById('manual-download-code');
                const manualChmodCode = document.getElementById('manual-chmod-code');
                const manualRunCode = document.getElementById('manual-run-code');
                const stableLabel = document.getElementById('stable-label');
                const betaLabel = document.getElementById('beta-label');

                if (isBeta && betaAvailable) {
                    betaWarning.style.display = 'block';
                    quickCode.textContent = 'curl -sSL https://plexdev.live/beta.sh | bash -i';
                    manualDownloadCode.textContent = 'curl -sSL -o beta.sh https://plexdev.live/beta.sh';
                    manualChmodCode.textContent = 'chmod +x beta.sh';
                    manualRunCode.textContent = './beta.sh';
                    stableLabel.style.opacity = '0.5';
                    betaLabel.style.opacity = '1';
                } else {
                    // Force back to stable if beta isn't available or toggle is off
                    document.getElementById('version-toggle').checked = false; // Ensure toggle is off if beta not available
                    betaWarning.style.display = 'none';
                    quickCode.textContent = 'curl -sSL https://plexdev.live/install.sh | bash -i';
                    manualDownloadCode.textContent = 'curl -sSL -o install.sh https://plexdev.live/install.sh';
                    manualChmodCode.textContent = 'chmod +x install.sh';
                    manualRunCode.textContent = './install.sh';
                    stableLabel.style.opacity = '1';
                    betaLabel.style.opacity = '0.5';
                }
            }

            // Initial setup on page load
            window.onload = () => {
                toggleVersion(); // Set initial state based on toggle (default is stable)
            };
        </script>
    </body>
    </html>
  `);
});

// --- Simple Guide Route ---
app.get('/guide', (req, res) => {
  res.send(`
    <!DOCTYPE html>
    <html>
    <head>
        <title>Simple Guide - PlexDev.live Unofficial Installer</title>
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <style>
            /* --- Reuse Styles from Main Page --- */
             :root { --bg-primary: #121212; --bg-secondary: #1e1e1e; --text-primary: #e4e4e4; --text-secondary: #a0a0a0; --accent: #3498db; --accent-dark: #2980b9; --success: #2ecc71; --warning: #f39c12; --danger: #e74c3c; --card-bg: #252525; --border-color: #333; }
            * { box-sizing: border-box; margin: 0; padding: 0; }
            body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; line-height: 1.6; color: var(--text-primary); background-color: var(--bg-primary); max-width: 900px; margin: 0 auto; padding: 20px; }
            h1, h2, h3 { color: var(--text-primary); margin: 1.5rem 0 1rem 0; }
            h1 { font-size: 2.5rem; border-bottom: 2px solid var(--accent); padding-bottom: 10px; margin-bottom: 1.5rem; }
            h2 { font-size: 1.8rem; margin-top: 2rem; }
            p, li { margin: 1rem 0; color: var(--text-secondary); }
            ul { margin-left: 30px; }
            a { color: var(--accent); text-decoration: none; }
            a:hover { color: var(--accent-dark); text-decoration: underline; }
            .code-block { background-color: var(--bg-secondary); border: 1px solid var(--border-color); border-radius: 6px; padding: 15px; margin: 15px 0; font-family: 'Consolas', 'Courier New', monospace; overflow-x: auto; position: relative; }
            .code-block code { color: #f1c40f; }
            .code-block::before { content: "$ "; opacity: 0.5; }
            .card { background-color: var(--card-bg); border-radius: 8px; padding: 20px; margin: 20px 0; border-left: 4px solid var(--accent); }
            .warning { background-color: rgba(243, 156, 18, 0.1); border-left: 4px solid var(--warning); padding: 15px; margin: 20px 0; border-radius: 4px; }
            .danger { background-color: rgba(231, 76, 60, 0.1); border-left: 4px solid var(--danger); padding: 15px; margin: 20px 0; border-radius: 4px; }
            strong { color: var(--text-primary); }
            footer { margin-top: 40px; color: var(--text-secondary); text-align: center; border-top: 1px solid var(--border-color); padding-top: 20px; font-size: 0.9rem; }
        </style>
    </head>
    <body>
        <h1>Super Simple Guide to the Installer</h1>
        <p>Hey there! So you want to install some cool stuff from PlexDevelopment, but maybe you're not a computer wizard? No problem! This guide explains things like you're five (okay, maybe ten).</p>
        <p><a href="/">&laquo; Back to Installer</a></p>

        <h2>What is This Thing?</h2>
        <div class="card">
            <p>Think of this installer as a helpful robot. You tell it what Plex product you want (like PlexTickets or PlexStore), and it does all the tricky setup stuff on your Linux server for you.</p>
            <p>Normally, setting these things up involves lots of typing weird commands. This robot does most of that typing for you!</p>
            <div class="danger">
                <strong>Super Important:</strong> This robot is built by someone else (bali0531), NOT the official PlexDevelopment team. It's like getting help from a friendly neighbor instead of the official company. It usually works great, but it's not official support.
            </div>
        </div>

        <h2>How Do I Use the Robot? (Quick Install)</h2>
        <div class="card">
            <p>This is the easiest way. It's like telling your robot helper, "Go do the thing!"</p>
            <ol>
                <li><strong>Connect to Your Server:</strong> You need to be talking to your Linux server. This usually means using a program like PuTTY (on Windows) or Terminal (on Mac/Linux) and logging in. You'll see a blinking cursor waiting for commands.</li>
                <li><strong>Copy the Magic Spell:</strong> Go back to the <a href="/">main installer page</a>. Find the black box with the command inside (it starts with <code>curl</code>). Click the "Copy" button next to it.</li>
                <li><strong>Paste and Go:</strong> Go back to your server terminal window. Right-click (or use Shift+Insert or Cmd+V) to paste the command you copied. It should look something like this:
                    <div class="code-block"><code>curl -sSL https://plexdev.live/install.sh | bash -i</code></div>
                    (Or it might say <code>beta.sh</code> if you chose the Beta option).
                </li>
                <li><strong>Hit Enter:</strong> Press the Enter key on your keyboard.</li>
                <li><strong>Follow Instructions:</strong> The robot (installer script) will start working. It will ask you some questions, like:
                    <ul>
                        <li>Which product do you want to install?</li>
                        <li>What website address (domain) do you want to use? (e.g., <code>tickets.mycoolsite.com</code>)</li>
                        <li>What's your email? (For website security stuff)</li>
                    </ul>
                    Just answer the questions carefully. If you're unsure, the script often suggests a default answer.
                </li>
            </ol>
            <p>That's it for starting! The robot does the rest.</p>
        </div>

        <h2>What Does the Robot Actually Do?</h2>
        <div class="card">
            <p>While you watch the text scroll by, the installer is busy doing these things:</p>
            <ul>
                <li><strong>Checks Your Server:</strong> Figures out what kind of Linux you have (like Ubuntu, Debian, etc.).</li>
                <li><strong>Gets Tools:</strong> Installs programs your new Plex product needs to run (like Node.js, which is a runtime; Nginx, which is a web server; Certbot, for security).</li>
                <li><strong>Unpacks the Product:</strong> Takes the product files (which you provide as a .zip or .rar) and puts them in the right place (usually <code>/var/www/plex/PRODUCT_NAME</code>).</li>
                <li><strong>Installs More Tools (for the product):</strong> Runs <code>npm install</code> inside the product's folder to get any extra bits it needs.</li>
                <li><strong>Sets Up the Website:</strong> Configures the Nginx web server so when people visit your chosen domain (like <code>tickets.mycoolsite.com</code>), they see the Plex product.</li>
                <li><strong>Adds Security (HTTPS):</strong> Uses Certbot and Let's Encrypt to get a free SSL certificate. This makes the little padlock appear in browsers and keeps connections secure (HTTPS instead of HTTP).</li>
                <li><strong>Makes it Run Forever (Almost):</strong> Creates a 'systemd service'. This is like telling the server, "Make sure this program is always running, even if you restart."</li>
            </ul>
        </div>

        <h2>Stable vs. Beta? What's That?</h2>
        <div class="card">
            <p>On the main page, you might see a switch for "Stable" and "Beta".</p>
            <ul>
                <li><strong>Stable:</strong> This is the version that's been tested more. It's less likely to have weird problems. <strong>Use this one if you're not sure.</strong></li>
                <li><strong>Beta:</strong> This is a newer version, like a test drive. It might have cool new features, but it might also break sometimes. Only use this if you like experimenting or if the stable one isn't working for you.</li>
            </ul>
            <div class="warning">
                If you use Beta, be prepared for things to maybe go wrong!
            </div>
        </div>

        <h2>Okay, It Finished. Now What?</h2>
        <div class="card">
            <p>If everything went well, the script will tell you it's done and usually show you:</p>
            <ul>
                <li><strong>The Website Address:</strong> The <code>https://your.domain.com</code> address you can visit in your web browser.</li>
                <li><strong>How to Control the Service:</strong> Commands like:
                    <ul>
                        <li><code>sudo systemctl status plex-PRODUCT_NAME</code> (Check if it's running)</li>
                        <li><code>sudo systemctl stop plex-PRODUCT_NAME</code> (Stop it)</li>
                        <li><code>sudo systemctl start plex-PRODUCT_NAME</code> (Start it)</li>
                        <li><code>sudo systemctl restart plex-PRODUCT_NAME</code> (Restart it if you change config)</li>
                    </ul>
                    (Replace <code>PRODUCT_NAME</code> with the actual product, like <code>plextickets</code>).
                </li>
                <li><strong>How to See Logs:</strong> A command like <code>sudo journalctl -u plex-PRODUCT_NAME -f</code> lets you see messages from the running program, useful if something seems wrong.</li>
                <li><strong>Configuration File:</strong> It might tell you where the product's settings file is (like <code>config.yml</code>) so you can customize it later.</li>
            </ul>
            <p>Go visit the website address it gave you! You should see your new Plex product running.</p>
        </div>

        <h2>Something Went Wrong!</h2>
        <div class="card">
            <p>Uh oh. Sometimes things break.</p>
            <ul>
                <li><strong>Read the Red Text:</strong> The installer usually prints error messages in <span style="color: var(--danger);">RED</span>. Read those carefully, they often give clues.</li>
                <li><strong>Check Logs:</strong> If the product installed but isn't working right, use the <code>journalctl</code> command mentioned above to see its logs.</li>
                <li><strong>Ask for Help (Unofficially):</strong> Since this is unofficial, you can try asking in places where the creator (bali0531) might be, but remember there's no guarantee of official support.</li>
                <li><strong>Try Again?:</strong> Sometimes just running the installer again fixes temporary glitches. If it asks to remove an existing installation first, say yes.</li>
            </ul>
        </div>

        <footer>
            Hope this helps! Remember, this is unofficial. | <a href="/">Back to Installer</a> | <a href="https://plexdevelopment.net" target="_blank">Official Site</a>
        </footer>
    </body>
    </html>
  `);
});


// --- Script Serving Routes (Keep existing logic) ---
app.get('/install.sh', (req, res) => {
  const filePath = path.join(__dirname, 'install.sh');
  const data = readFileSafe(filePath);

  if (data !== null) {
    res.setHeader('Content-Type', 'text/plain; charset=utf-8');
    res.setHeader('Content-Disposition', 'inline; filename="install.sh"');
    res.send(data);
  } else {
    res.status(404).send('Stable installer script (install.sh) not found or unreadable.');
  }
});

app.get('/beta.sh', (req, res) => {
  const filePath = path.join(__dirname, 'beta.sh');
  const data = readFileSafe(filePath); // Uses the safe reader

  if (data !== null) {
    res.setHeader('Content-Type', 'text/plain; charset=utf-8');
    res.setHeader('Content-Disposition', 'inline; filename="beta.sh"');
    res.send(data);
  } else {
    // If readFileSafe returned null, it means it doesn't exist or wasn't readable
    res.status(404).send('Beta installer script (beta.sh) not found or unreadable.');
  }
});

app.get('/.well-known/discord', (req, res) => {
  const filePath path.join(__dirname, '.well-known/discord');
  const data = readFileSafe(filePath);
  res.send(data);
});

// --- Server Start ---
app.listen(port, () => {
  console.log(`Server running at http://localhost:${port}/`);
  console.log(`Simple guide available at http://localhost:${port}/guide`);
  console.log(`Stable installer script available at http://localhost:${port}/install.sh`);
  if (betaScriptExists) {
    console.log(`Beta installer script available at http://localhost:${port}/beta.sh`);
  } else {
    console.warn('Beta installer script (beta.sh) not found. Beta toggle will be disabled.');
  }
});
