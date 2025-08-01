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
    console.warn(`File not found or unreadable: ${filePath}`); // Log warning if file missing
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
  const indexPath = path.join(__dirname, 'index.html');
  let indexHtmlContent = readFileSafe(indexPath);

  if (indexHtmlContent) {
    // Inject the betaAvailable variable into the HTML before sending
    // Replace the placeholder "__BETA_AVAILABLE__" with the actual boolean value
    indexHtmlContent = indexHtmlContent.replace('__BETA_AVAILABLE__', betaScriptExists.toString());
    res.setHeader('Content-Type', 'text/html; charset=utf-8');
    res.send(indexHtmlContent);
  } else {
    res.status(500).send('Error: index.html file is missing or unreadable.');
  }
});

// --- Simple Guide Route ---
app.get('/guide', (req, res) => {
  const guidePath = path.join(__dirname, 'guide.html');
  // No dynamic data needed for the guide, just send the file
  res.sendFile(guidePath, (err) => {
    if (err) {
      console.error("Error sending guide.html:", err);
      if (!res.headersSent) { // Avoid sending multiple responses
         res.status(404).send('Guide page not found.');
      }
    }
  });
});


// --- Script Serving Routes ---
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
// --- Script Serving Routes ---
app.get('/.well-known/discord', (req, res) => {
  const filePath = path.join(__dirname, '.well-known/discord');
  const data = readFileSafe(filePath);

  if (data !== null) {
    res.send(data);
  } else {
    res.status(404).send('Well... shit.....');
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

// --- Affiliate Banner Image Route ---
app.get('/images.jpeg', (req, res) => {
  const filePath = path.join(__dirname, 'images.jpeg');
  
  if (fs.existsSync(filePath)) {
    res.setHeader('Content-Type', 'image/jpeg');
    res.setHeader('Cache-Control', 'public, max-age=3600'); // 1 hour cache
    res.sendFile(filePath);
  } else {
    res.status(404).send('ZAP-Hosting banner image not found.');
  }
});

// --- Ads.txt Route ---
app.get('/ads.txt', (req, res) => {
  const filePath = path.join(__dirname, 'ads.txt');
  const data = readFileSafe(filePath);

  if (data !== null) {
    res.setHeader('Content-Type', 'text/plain; charset=utf-8');
    res.setHeader('Cache-Control', 'public, max-age=86400'); // 24 hour cache
    res.send(data);
  } else {
    res.status(404).send('ads.txt file not found.');
  }
});


// --- Server Start ---
app.listen(port, () => {
  console.log(`Server running at http://localhost:${port}/`);
  console.log(`Simple guide available at http://localhost:${port}/guide`);
  console.log(`Stable installer script available at http://localhost:${port}/install.sh`);
  if (betaScriptExists) {
    console.log(`Beta installer script available at http://localhost:${port}/beta.sh`);
  } else {
    console.warn('Beta installer script (beta.sh) not found. Beta toggle will be disabled on the website.');
  }
});
