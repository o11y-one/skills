const http = require('node:http');

const port = Number(process.env.PORT || 3101);
http
  .createServer((req, res) => {
    res.writeHead(200, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({ service: 'orders' }));
  })
  .listen(port, '127.0.0.1', () => console.log(`eval-orders listening on ${port}`));
