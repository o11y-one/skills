const http = require('node:http');

const port = Number(process.env.PORT || 3102);
http
  .createServer((req, res) => {
    res.writeHead(200, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({ service: 'billing' }));
  })
  .listen(port, '127.0.0.1', () => console.log(`eval-billing listening on ${port}`));
