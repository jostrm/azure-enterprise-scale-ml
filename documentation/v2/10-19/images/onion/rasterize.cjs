// Offline CPU rasterization with the pinned @resvg/resvg-js (no browser capture).
// Usage: node rasterize.cjs <jobs.json> [font-dir]; each job is {"svg": path, "png": path}.
const fs = require('node:fs');
const path = require('node:path');
const { Resvg } = require('@resvg/resvg-js');

const [jobsFile, fontDir] = process.argv.slice(2);
const jobs = JSON.parse(fs.readFileSync(jobsFile, 'utf8'));
const fontFiles = fontDir ? ['OpenSans-Regular.ttf', 'OpenSans-Semibold.ttf'].map((name) => path.join(fontDir, name)) : [];
for (const job of jobs) {
  const renderer = new Resvg(fs.readFileSync(job.svg, 'utf8'), {
    font: { loadSystemFonts: fontFiles.length === 0, fontFiles, defaultFontFamily: fontFiles.length ? 'Open Sans' : 'DejaVu Sans' },
  });
  fs.writeFileSync(job.png, renderer.render().asPng());
}
console.log(`Rasterized ${jobs.length} SVG file(s) with resvg 2.6.2${fontFiles.length ? ' and Open Sans' : ' and system fonts'}.`);
