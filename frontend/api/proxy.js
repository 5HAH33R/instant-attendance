export default async function handler(req, res) {
  const backendUrl = process.env.VITE_BACKEND_URL;

  if (!backendUrl) {
    return res.status(500).json({ error: 'Backend URL not configured' });
  }

  const path = req.query.path || '';
  const targetUrl = `${backendUrl}/${Array.isArray(path) ? path.join('/') : path}`;

  try {
    // Build sanitized headers - don't forward sensitive proxy headers
    const forwardedHeaders = {};
    const skipHeaders = ['host', 'x-forwarded-for', 'x-forwarded-proto', 'x-real-ip', 'connection'];
    for (const [key, value] of Object.entries(req.headers)) {
      if (!skipHeaders.includes(key.toLowerCase())) {
        forwardedHeaders[key] = value;
      }
    }

    const options = {
      method: req.method,
      headers: {
        ...forwardedHeaders,
        host: new URL(backendUrl).host,
      },
    };

    // Forward the request body if present
    if (req.body && req.method !== 'GET') {
      options.body = JSON.stringify(req.body);
    }

    const response = await fetch(targetUrl, options);

    // Forward response headers (except hop-by-hop headers)
    const headers = {};
    const excludeHeaders = ['content-encoding', 'transfer-encoding', 'connection', 'keep-alive'];

    response.headers.forEach((value, key) => {
      if (!excludeHeaders.includes(key.toLowerCase())) {
        headers[key] = value;
      }
    });

    // Copy specific headers we need
    if (response.headers.get('X-Session-Token')) {
      headers['X-Session-Token'] = response.headers.get('X-Session-Token');
    }

    res.status(response.status);

    // Set headers
    Object.entries(headers).forEach(([key, value]) => {
      res.setHeader(key, value);
    });

    // Forward the response body
    const buffer = await response.arrayBuffer();
    res.send(Buffer.from(buffer));
  } catch (error) {
    console.error('Proxy error:', error.message);
    res.status(500).json({ error: 'Proxy request failed' });
  }
}
