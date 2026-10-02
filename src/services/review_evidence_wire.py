"""Lossless prompt-only span addressing; canonical importer format unchanged."""
import json,re
SEGMENT_VERSION='lossless-character-spans-v1'
MAX_CHARS=180

def segment(document_id,body):
 if not isinstance(body,str) or not body.strip():raise ValueError('nonempty body required')
 # Punctuation/newlines give boundaries; decimals stay intact. Long unpunctuated
 # runs use codepoint windows, preferring whitespace when available. No cleanup.
 ends=[m.end() for m in re.finditer(r'[.!?。]+(?!\d)\s*|\n+',body)]+[len(body)]
 spans=[];start=0
 for end in sorted(set(ends)):
  while end-start>MAX_CHARS:
   stop=start+MAX_CHARS;spaces=[m.end() for m in re.finditer(r'\s+',body[start:stop])]
   if spaces and spaces[-1]>=MAX_CHARS//2:stop=start+spaces[-1]
   spans.append((start,stop));start=stop
  if end>start:spans.append((start,end));start=end
 # Attach rare whitespace-only piece to previous/next so every ID is eligible.
 clean=[]
 for a,b in spans:
  if not body[a:b].strip() and clean:clean[-1]=(clean[-1][0],b)
  elif clean and not body[clean[-1][0]:clean[-1][1]].strip():clean[-1]=(clean[-1][0],b)
  else:clean.append((a,b))
 result=[{'evidence_id':f'{document_id}:s{i:04d}','start':a,'end':b,'text':body[a:b]} for i,(a,b) in enumerate(clean,1)]
 assert ''.join(s['text'] for s in result)==body
 assert result[0]['start']==0 and result[-1]['end']==len(body)
 assert all(s['text'].strip() and body[s['start']:s['end']]==s['text'] for s in result)
 return result

def wire_input(inp):
 return {**inp,'segment_version':SEGMENT_VERSION,'span_boundary_unit':'Python Unicode codepoints, start inclusive/end exclusive','reviews':[{**{k:v for k,v in r.items() if k!='body'},'evidence_spans':segment(r['document_id'],r['body'])} for r in inp['reviews']]}

def reconstruct_wire(wire,canonical):
 # Frozen source is authoritative for completeness and order, not model text.
 expected=wire_input(canonical)
 if wire!=expected:raise ValueError('omitted/reordered/unknown/cross-document spans or wire/source fields differ')
 reviews=[]
 for wr,src in zip(wire['reviews'],canonical['reviews']):
  body=''.join(s['text'] for s in wr['evidence_spans'])
  if body!=src['body']:raise ValueError('lossless source reconstruction failed')
  reviews.append({**{k:v for k,v in wr.items() if k!='evidence_spans'},'body':body})
 result={k:wire[k] for k in ['analysis_version','mode','rules']};result['reviews']=reviews
 if result!=canonical:raise ValueError('canonical reconstruction fields differ')
 return result

def restore(inp,raw):
 if not isinstance(raw,dict) or set(raw)!={'analysis_version','results'}:raise ValueError('wire top-level fields')
 if raw['analysis_version']!=inp['analysis_version']:raise ValueError('wire version')
 if not isinstance(raw['results'],list) or len(raw['results'])!=len(inp['reviews']):raise ValueError('wire coverage')
 results=[]
 for review,result in zip(inp['reviews'],raw['results']):
  if not isinstance(result,dict) or set(result)!={'document_id','result','observations','diagnostics'} or result['document_id']!=review['document_id']:raise ValueError('wire result fields/order')
  spans={s['evidence_id']:s['text'] for s in segment(review['document_id'],review['body'])}
  def exact(eid):
   if not isinstance(eid,str) or eid not in spans:raise ValueError('unknown or cross-document evidence ID')
   return spans[eid]
  if not isinstance(result['observations'],list) or not isinstance(result['diagnostics'],list):raise ValueError('wire arrays')
  obs=[];diags=[]
  for o in result['observations']:
   if not isinstance(o,dict) or set(o)!={'rule_id','observation_text','direction','evidence_ids'}:raise ValueError('wire observation fields')
   ids=o['evidence_ids']
   if not isinstance(ids,list) or not ids or not all(isinstance(i,str) for i in ids) or len(set(ids))!=len(ids):raise ValueError('wire nonempty unique evidence IDs')
   obs.append({'rule_id':o['rule_id'],'observation_text':o['observation_text'],'direction':o['direction'],'evidence_sentences':[exact(i) for i in ids]})
  for d in result['diagnostics']:
   if not isinstance(d,dict) or set(d)!={'code','evidence_id','detail'}:raise ValueError('wire diagnostic fields')
   diags.append({'code':d['code'],'evidence_text':None if d['evidence_id'] is None else exact(d['evidence_id']),'detail':d['detail']})
  results.append({'document_id':result['document_id'],'result':result['result'],'observations':obs,'diagnostics':diags})
 return {'analysis_version':raw['analysis_version'],'results':results}
