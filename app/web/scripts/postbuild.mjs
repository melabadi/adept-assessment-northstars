// Vite empties the API's wwwroot folder on every build (emptyOutDir). Recreate the tracked
// placeholder so the folder stays in git and `git status` stays clean after a build.
import { existsSync, mkdirSync, writeFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

const outDir = fileURLToPath(new URL('../../src/RequestHub.Api/wwwroot/', import.meta.url));
const placeholder = fileURLToPath(new URL('../../src/RequestHub.Api/wwwroot/.gitkeep', import.meta.url));

mkdirSync(outDir, { recursive: true });
if (!existsSync(placeholder)) {
  writeFileSync(placeholder, '');
}

console.log(`postbuild: ensured ${placeholder}`);
