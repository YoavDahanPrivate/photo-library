const assert=require('node:assert/strict');
const {withMediaFilter:w,selectedMediaFilter:s}=require('../qa-media-filter/mediaFilter.js');
assert.equal(s(''), '');assert.equal(s('MediaType("photo")'),'photo');assert.equal(s('not MediaType("photo")'),'video');
assert.equal(s('Includes("Nadav") and MediaType("video")'),'video');
assert.equal(s('Includes("Nadav") and between May 2025 and April 2026'),'');
for(const source of ['MediaType("photo")','not MediaType("photo")','MediaType("photo") or MediaType("video")']){assert.equal(s(w(source,'video')),'video');assert.equal(w(source,''),'');}
const q='Includes("Nadav") and between May 2025 and April 2026 and MediaType("photo")';
const changed=w(q,'video');assert(changed.includes('Includes ( "Nadav" )'));assert(changed.includes('between May 2025 and April 2026'));assert(!changed.includes('"photo"'));assert.equal(s(changed),'video');
assert(w('Text("MediaType(\"photo\")")','video').includes('Text'));
assert(w('on or after May 2025 and MediaType("photo")','').includes('on or after May 2025'));
console.log('Media filter regression checks passed');
