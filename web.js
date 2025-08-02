const express = require('express');
const fs = require('fs');
const path = require('path');
const app = express();
const port = process.env.PORT || 31234;

// Enable trust proxy for better performance behind reverse proxies
app.set('trust proxy', 1);

// Disable unnecessary headers for better performance
app.disable('x-powered-by');

// Add compression middleware (if available)
try {
  const compression = require('compression');
  app.use(compression({
    threshold: 1024, // Only compress responses > 1KB
    level: 6, // Balanced compression level
    filter: (req, res) => {
      // Don't compress if the client doesn't accept compressed responses
      if (req.headers['x-no-compression']) {
        return false;
      }
      // Use compression filter function
      return compression.filter(req, res);
    }
  }));
} catch (err) {
  console.log('Compression middleware not available, continuing without compression');
}

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
    
    // Add performance headers
    res.setHeader('Content-Type', 'text/html; charset=utf-8');
    res.setHeader('Cache-Control', 'public, max-age=3600'); // Cache for 1 hour
    res.setHeader('X-Content-Type-Options', 'nosniff');
    res.setHeader('X-Frame-Options', 'DENY');
    res.setHeader('X-XSS-Protection', '1; mode=block');
    
    res.send(indexHtmlContent);
  } else {
    res.status(500).send('Error: index.html file is missing or unreadable.');
  }
});

// --- Simple Guide Route ---
app.get('/guide', (req, res) => {
  const guidePath = path.join(__dirname, 'guide.html');
  
  // Add performance headers
  res.setHeader('Cache-Control', 'public, max-age=3600');
  res.setHeader('X-Content-Type-Options', 'nosniff');
  res.setHeader('X-Frame-Options', 'DENY');
  res.setHeader('X-XSS-Protection', '1; mode=block');
  
  res.sendFile(guidePath, (err) => {
    if (err) {
      console.error("Error sending guide.html:", err);
      if (!res.headersSent) {
         res.status(404).send('Guide page not found.');
      }
    }
  });
});

// --- Privacy Policy Route ---
app.get('/privacy.html', (req, res) => {
  const privacyPath = path.join(__dirname, 'privacy.html');
  
  res.setHeader('Cache-Control', 'public, max-age=86400'); // 24 hours for legal pages
  res.setHeader('X-Content-Type-Options', 'nosniff');
  res.setHeader('X-Frame-Options', 'DENY');
  res.setHeader('X-XSS-Protection', '1; mode=block');
  
  res.sendFile(privacyPath, (err) => {
    if (err) {
      console.error("Error sending privacy.html:", err);
      if (!res.headersSent) {
        res.status(404).send('Privacy Policy page not found.');
      }
    }
  });
});

// --- Terms of Service Route ---
app.get('/terms.html', (req, res) => {
  const termsPath = path.join(__dirname, 'terms.html');
  
  res.setHeader('Cache-Control', 'public, max-age=86400'); // 24 hours for legal pages
  res.setHeader('X-Content-Type-Options', 'nosniff');
  res.setHeader('X-Frame-Options', 'DENY');
  res.setHeader('X-XSS-Protection', '1; mode=block');
  
  res.sendFile(termsPath, (err) => {
    if (err) {
      console.error("Error sending terms.html:", err);
      if (!res.headersSent) {
        res.status(404).send('Terms of Service page not found.');
      }
    }
  });
});

// --- FAQ Route ---
app.get('/faq.html', (req, res) => {
  const faqPath = path.join(__dirname, 'faq.html');
  
  res.setHeader('Cache-Control', 'public, max-age=3600'); // 1 hour for FAQ
  res.setHeader('X-Content-Type-Options', 'nosniff');
  res.setHeader('X-Frame-Options', 'DENY');
  res.setHeader('X-XSS-Protection', '1; mode=block');
  
  res.sendFile(faqPath, (err) => {
    if (err) {
      console.error("Error sending faq.html:", err);
      if (!res.headersSent) {
        res.status(404).send('FAQ page not found.');
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
    res.setHeader('Cache-Control', 'public, max-age=1800'); // 30 minutes for scripts
    res.setHeader('X-Content-Type-Options', 'nosniff');
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
    res.setHeader('Cache-Control', 'public, max-age=1800'); // 30 minutes for scripts
    res.setHeader('X-Content-Type-Options', 'nosniff');
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
    res.setHeader('Cache-Control', 'public, max-age=31536000'); // 1 year cache
    res.setHeader('Expires', new Date(Date.now() + 31536000000).toUTCString()); // 1 year expiry
    res.setHeader('ETag', '"plexdev-banner-v1"'); // Add ETag for better caching
    res.sendFile(filePath);
  } else {
    res.status(404).send('ZAP-Hosting banner image not found.');
  }
});

// --- Optimized Images Routes ---
app.get('/images-optimized.jpeg', (req, res) => {
  const filePath = path.join(__dirname, 'images-optimized.jpeg');
  
  if (fs.existsSync(filePath)) {
    res.setHeader('Content-Type', 'image/jpeg');
    res.setHeader('Cache-Control', 'public, max-age=31536000'); // 1 year cache
    res.setHeader('Expires', new Date(Date.now() + 31536000000).toUTCString());
    res.setHeader('ETag', '"plexdev-banner-optimized-v1"');
    res.sendFile(filePath);
  } else {
    res.status(404).send('Optimized banner image not found.');
  }
});

app.get('/images-optimized.webp', (req, res) => {
  const filePath = path.join(__dirname, 'images-optimized.webp');
  
  if (fs.existsSync(filePath)) {
    res.setHeader('Content-Type', 'image/webp');
    res.setHeader('Cache-Control', 'public, max-age=31536000'); // 1 year cache
    res.setHeader('Expires', new Date(Date.now() + 31536000000).toUTCString());
    res.setHeader('ETag', '"plexdev-banner-webp-v1"');
    res.sendFile(filePath);
  } else {
    res.status(404).send('WebP banner image not found.');
  }
});

// --- High-DPI Images Routes ---
app.get('/images-1.5x.jpeg', (req, res) => {
  const filePath = path.join(__dirname, 'images-1.5x.jpeg');
  
  if (fs.existsSync(filePath)) {
    res.setHeader('Content-Type', 'image/jpeg');
    res.setHeader('Cache-Control', 'public, max-age=31536000'); // 1 year cache
    res.setHeader('Expires', new Date(Date.now() + 31536000000).toUTCString());
    res.setHeader('ETag', '"plexdev-banner-1.5x-v1"');
    res.sendFile(filePath);
  } else {
    res.status(404).send('1.5x banner image not found.');
  }
});

app.get('/images-1.5x.webp', (req, res) => {
  const filePath = path.join(__dirname, 'images-1.5x.webp');
  
  if (fs.existsSync(filePath)) {
    res.setHeader('Content-Type', 'image/webp');
    res.setHeader('Cache-Control', 'public, max-age=31536000');
    res.setHeader('Expires', new Date(Date.now() + 31536000000).toUTCString());
    res.setHeader('ETag', '"plexdev-banner-1.5x-webp-v1"');
    res.sendFile(filePath);
  } else {
    res.status(404).send('1.5x WebP banner image not found.');
  }
});

app.get('/images-2x.jpeg', (req, res) => {
  const filePath = path.join(__dirname, 'images-2x.jpeg');
  
  if (fs.existsSync(filePath)) {
    res.setHeader('Content-Type', 'image/jpeg');
    res.setHeader('Cache-Control', 'public, max-age=31536000');
    res.setHeader('Expires', new Date(Date.now() + 31536000000).toUTCString());
    res.setHeader('ETag', '"plexdev-banner-2x-v1"');
    res.sendFile(filePath);
  } else {
    res.status(404).send('2x banner image not found.');
  }
});

app.get('/images-2x.webp', (req, res) => {
  const filePath = path.join(__dirname, 'images-2x.webp');
  
  if (fs.existsSync(filePath)) {
    res.setHeader('Content-Type', 'image/webp');
    res.setHeader('Cache-Control', 'public, max-age=31536000');
    res.setHeader('Expires', new Date(Date.now() + 31536000000).toUTCString());
    res.setHeader('ETag', '"plexdev-banner-2x-webp-v1"');
    res.sendFile(filePath);
  } else {
    res.status(404).send('2x WebP banner image not found.');
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
