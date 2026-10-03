import fs from 'node:fs/promises';
import {FileBlob, PresentationFile} from '@oai/artifact-tool';
const root='C:/web_workspace/skn_final';
const p=await PresentationFile.importPptx(await FileBlob.load(root+'/output/TrueFit_사업모델_발표자료.pptx'));
const dir=root+'/.ppt-build/truefit/final-renders';
await fs.mkdir(dir,{recursive:true});
for(let i=0;i<p.slides.items.length;i++){
 const png=await p.export({slide:p.slides.items[i],format:'png',scale:1});
 await fs.writeFile(dir+'/'+String(i+1).padStart(2,'0')+'.png',new Uint8Array(await png.arrayBuffer()));
 console.log('Final slide',i+1);
}
