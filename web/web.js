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
app.get('/setup.sh', (req, res) => {
  const filePath = path.join(__dirname, 'setup.sh');
  const data = readFileSafe(filePath);

  if (data !== null) {
    res.setHeader('Content-Type', 'text/plain; charset=utf-8');
    res.setHeader('Content-Disposition', 'inline; filename="setup.sh"');
    res.setHeader('Cache-Control', 'public, max-age=1800'); // 30 minutes for scripts
    res.setHeader('X-Content-Type-Options', 'nosniff');
    res.send(data);
  } else {
    res.status(404).send('Setup script (setup.sh) not found or unreadable.');
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

// --- Security.txt Route ---
app.get('/.well-known/security.txt', (req, res) => {
  const filePath = path.join(__dirname, '.well-known/security.txt');
  const data = readFileSafe(filePath);

  if (data !== null) {
    res.setHeader('Content-Type', 'text/plain; charset=utf-8');
    res.setHeader('Cache-Control', 'public, max-age=86400'); // 24 hour cache
    res.setHeader('X-Content-Type-Options', 'nosniff');
    res.send(data);
  } else {
    res.status(404).send('security.txt file not found.');
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

// --- Robots.txt Route ---
app.get('/robots.txt', (req, res) => {
  const filePath = path.join(__dirname, 'robots.txt');
  const data = readFileSafe(filePath);

  if (data !== null) {
    res.setHeader('Content-Type', 'text/plain; charset=utf-8');
    res.setHeader('Cache-Control', 'public, max-age=86400'); // 24 hour cache for robots.txt
    res.setHeader('X-Content-Type-Options', 'nosniff');
    res.send(data);
  } else {
    res.status(404).send('robots.txt file not found.');
  }
});

// --- Sitemap.xml Route ---
app.get('/sitemap.xml', (req, res) => {
  const filePath = path.join(__dirname, 'sitemap.xml');
  const data = readFileSafe(filePath);

  if (data !== null) {
    res.setHeader('Content-Type', 'application/xml; charset=utf-8');
    res.setHeader('Cache-Control', 'public, max-age=86400'); // 24 hour cache for sitemap
    res.setHeader('X-Content-Type-Options', 'nosniff');
    res.send(data);
  } else {
    res.status(404).send('sitemap.xml file not found.');
  }
});

// --- Privacy Policy Route ---
// --- Legacy AdSense privacy URL -> redirect to main Privacy Policy ---
app.get('/privacy-policy.html', (req, res) => {
  res.redirect(301, '/privacy.html');
});

// --- Security.txt Route ---
app.get('/.well-known/security.txt', (req, res) => {
  res.setHeader('Content-Type', 'text/plain; charset=utf-8');
  res.setHeader('Cache-Control', 'public, max-age=86400'); // 24 hours

  const securityTxt = `Contact: mailto:support@plexdev.live
Expires: 2025-12-31T23:59:59.000Z
Preferred-Languages: en, hu
Canonical: https://plexdev.live/.well-known/security.txt
Policy: https://plexdev.live/privacy.html
Acknowledgments: https://plexdev.live/

# Security contact information for plexdev.live
# Following RFC 9116 standard for security.txt`;

  res.send(securityTxt);
});

// --- Favicon Route (simple fallback) ---
app.get('/favicon.ico', (req, res) => {
  // Return a 204 (No Content) to prevent 404 errors for favicon requests
  res.status(204).end();
});

// --- 404 Handler (should be last route) ---
app.use((req, res) => {
  res.status(404);
  res.setHeader('Content-Type', 'text/html; charset=utf-8');
  res.setHeader('X-Content-Type-Options', 'nosniff');
  res.setHeader('X-Frame-Options', 'DENY');
  res.setHeader('X-XSS-Protection', '1; mode=block');
  
  const notFoundHtml = `
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>404 - Page Not Found | PlexDev.live</title>
        <style>
            body { 
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; 
                background: #0a0a0a; 
                color: #f0f0f0; 
                text-align: center; 
                padding: 50px 20px; 
                margin: 0; 
            }
            .container { 
                max-width: 600px; 
                margin: 0 auto; 
                background: #1a1a1a; 
                padding: 40px; 
                border-radius: 12px; 
                border: 1px solid #333; 
            }
            h1 { 
                color: #00d4ff; 
                font-size: 4rem; 
                margin-bottom: 20px; 
            }
            p { 
                color: #b0b0b0; 
                font-size: 1.1rem; 
                line-height: 1.6; 
                margin-bottom: 30px; 
            }
            a { 
                color: #00d4ff; 
                text-decoration: none; 
                padding: 12px 24px; 
                border: 1px solid #00d4ff; 
                border-radius: 8px; 
                display: inline-block; 
                transition: all 0.3s ease; 
            }
            a:hover { 
                background: #00d4ff; 
                color: #0a0a0a; 
            }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>404</h1>
            <p><strong>Page Not Found</strong></p>
            <p>The requested URL "${req.originalUrl}" was not found on this server.</p>
            <p>This is a technical documentation site for Linux system administrators.</p>
            <a href="/">← Return to Homepage</a>
        </div>
    </body>
    </html>
  `;
  
  res.send(notFoundHtml);
});

// --- Server Start ---
app.listen(port, () => {
  console.log(`Server running at http://localhost:${port}/`);
  console.log(`Simple guide available at http://localhost:${port}/guide`);
  console.log(`Setup script available at http://localhost:${port}/setup.sh`);
  console.log(`SEO files available: robots.txt, sitemap.xml, ads.txt`);
});
