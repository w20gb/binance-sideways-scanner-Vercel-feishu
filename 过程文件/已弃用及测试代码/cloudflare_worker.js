
// Binance Proxy Worker
// Use this code in your Cloudflare Worker dash: https://dash.cloudflare.com/
// 1. Create a Service -> HTTP Router
// 2. Click "Quick Edit" and paste this code.
// 3. Save and Deploy.
// 4. Copy your Worker URL (e.g. https://binance-proxy.your-name.workers.dev)

addEventListener('fetch', event => {
  event.respondWith(handleRequest(event.request))
})

async function handleRequest(request) {
  const url = new URL(request.url)
  const path = url.pathname
  const search = url.search

  // Default target usually fapi (Futures) or api (Spot)
  // We determine target hostname based on path prefix
  let targetHost = 'api.binance.com' // Default to spot

  if (path.startsWith('/fapi')) {
    targetHost = 'fapi.binance.com'
  } else if (path.startsWith('/dapi')) {
    targetHost = 'dapi.binance.com'
  } else if (path.startsWith('/api')) {
    targetHost = 'api.binance.com'
  }

  // Construct target URL
  const targetUrl = `https://${targetHost}${path}${search}`

  // Re-create request to forward
  const newRequest = new Request(targetUrl, {
    method: request.method,
    headers: request.headers,
    body: request.body,
    redirect: 'follow'
  })

  // Add standard headers to mimic a browser/real client if needed,
  // though usually ccxt sends adequate headers.
  // Note: Cloudflare might strip some headers.

  try {
    const response = await fetch(newRequest)

    // Re-create response to return (mutable)
    const newResponse = new Response(response.body, response)

    // Add CORS headers to allow browser usage (if needed for dashboard)
    newResponse.headers.set('Access-Control-Allow-Origin', '*')
    newResponse.headers.set('Access-Control-Allow-Methods', 'GET, POST, PUT, DELETE, OPTIONS')
    newResponse.headers.set('Access-Control-Allow-Headers', '*')

    return newResponse
  } catch (e) {
    return new Response(JSON.stringify({ error: e.message }), { status: 500 })
  }
}
