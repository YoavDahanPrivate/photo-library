import { randomUUID } from 'node:crypto';
export default function releaseVersion() {
  const version = randomUUID();
  return {
    name: 'dahan-release-version',
    config() { return { define: { __APP_VERSION__: JSON.stringify(version) } }; },
    generateBundle() { this.emitFile({type:'asset',fileName:'version.json',source:JSON.stringify({version})}); },
  };
}
