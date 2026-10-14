import express from 'express';

const app = express();
app.get('/', (_req, res) => {
  res.json({ ok: true });
});
app.get('/health', (_req, res) => {
  res.json({ status: 'up' });
});

const port = Number(process.env.PORT ?? 3001);
app.listen(port, '127.0.0.1', () => {
  console.log(`eval-ts-api listening on ${port}`);
});
