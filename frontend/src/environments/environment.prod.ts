export const environment = {
  production: true,
  apiBase: '/api',  // nginx proxies /api/* to Django — no CORS needed
  // nginx proxies /ws/* to the daphne process; derive the host from the page origin.
  wsBase: typeof window !== 'undefined' ? `wss://${window.location.host}` : '',
};
