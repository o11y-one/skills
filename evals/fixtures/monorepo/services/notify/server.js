const http = require('node:http');

const port = Number(process.env.PORT || 3103);
http
  .createServer((req, res) => {
    res.writeHead(200, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({ service: 'notify' }));
  })
  .listen(port, '127.0.0.1', () => console.log(`eval-notify listening on ${port}`));
