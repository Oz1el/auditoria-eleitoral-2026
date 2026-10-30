const http = require('http');
const data = Buffer.from('UEsDBBQAAAAAAHy5XF0kxH5jGwAAABsAAAALAAAAZml4dHVyZS50eHRzeW50aGV0aWMgdHJhbnNwb3J0IGZpeHR1cmVQSwECFAMUAAAAAAB8uVxdJMR+YxsAAAAbAAAACwAAAAAAAAAAAAAAgAEAAAAAZml4dHVyZS50eHRQSwUGAAAAAAEAAQA5AAAARAAAAAAA', 'base64');
const counts = {};
http.createServer((req, res) => {
  const url = new URL(req.url, 'http://localhost');
  if (url.pathname === '/api/3/action/package_show') {
    const mode = url.searchParams.get('mode') || 'normal';
    counts[mode] = (counts[mode] || 0) + 1;
    if ((mode === '500' && counts[mode] <= 2) || mode === 'always500') {
      res.writeHead(500, {'Content-Type':'application/json'}); return res.end('{"error":"injected"}');
    }
    if (mode === '429' && counts[mode] === 1) {
      res.writeHead(429, {'Retry-After':'0'}); return res.end('injected rate limit');
    }
    res.writeHead(200, {'Content-Type':'application/json'});
    return res.end(JSON.stringify({success:true,result:{resources:[]}}));
  }
  if (url.pathname === '/archive.zip.sha512') {
    const hash = require('crypto').createHash('sha512').update(data).digest('hex');
    res.writeHead(200, {'Content-Type':'text/plain'}); return res.end(hash+'  archive.zip\n');
  }
  if (url.pathname === '/archive.zip') {
    const headers = {'Content-Type':'application/zip','Content-Length':data.length,'ETag':'"fixture-v1"','Accept-Ranges':'bytes'};
    if (req.method === 'HEAD') {res.writeHead(200,headers); return res.end();}
    const range = req.headers.range;
    if (range && !url.searchParams.get('ignore_range')) {
      const start = Number(range.match(/^bytes=(\d+)-$/)[1]);
      headers['Content-Range'] = `bytes ${start}-${data.length-1}/${data.length}`;
      headers['Content-Length'] = data.length-start;
      res.writeHead(206,headers); return res.end(data.subarray(start));
    }
    res.writeHead(200,headers); return res.end(data);
  }
  res.writeHead(501); res.end('path not modeled');
}).listen(process.env.PORT || 4500);
