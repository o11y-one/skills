const express = require('express');

const app = express();
app.get('/', (req, res) => res.json({ ok: true }));
app.get('/health', (req, res) => res.json({ status: 'up' }));

const port = Number(process.env.PORT || 3000);
app.listen(port, '127.0.0.1', () => console.log(`eval-node-api listening on ${port}`));
