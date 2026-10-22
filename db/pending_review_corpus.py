"""Emit bounded resumable Luna task groups, never replay saved first outputs."""
import argparse,json
from pathlib import Path
ROOT=Path('outputs/review_full_corpus/20261002_authorized')
def main():
 parser=argparse.ArgumentParser();parser.add_argument('--group-size',type=int,default=100);a=parser.parse_args()
 if not 1<=a.group_size<=100:raise ValueError('group size1..100')
 jobs=json.loads((ROOT/'batches/jobs.json').read_text());supp=ROOT/'supplement_literal_regional_alias/batches/jobs.json'
 if supp.exists():jobs+=json.loads(supp.read_text())
 registry=ROOT/'worker_assignments.json';assigned=json.loads(registry.read_text()) if registry.exists() else []
 active={p for t in assigned if t['status']=='active' for p in t['batch_paths']}
 unassigned=[j for j in jobs if not (Path(j['path'])/'first_raw.json').exists() and j['path'] not in active]
 result={'active_unfinished_batches':[j['path'] for j in jobs if j['path'] in active and not (Path(j['path'])/'first_raw.json').exists()],'unassigned_batches':len(unassigned),'groups':[{'model':'gpt-6-luna','reasoning_effort':'medium','fork_turns':'none','batch_paths':[j['path'] for j in unassigned[i:i+a.group_size]],'reviews':sum(len(j['document_ids']) for j in unassigned[i:i+a.group_size]),'contract':str(ROOT/'worker_contract.md'),'concurrency_max':2} for i in range(0,len(unassigned),a.group_size)]}
 (ROOT/'resume_queue.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');print(json.dumps({'unassigned_batches':len(unassigned),'active_unfinished_batches':len(result['active_unfinished_batches']),'groups':len(result['groups'])}))
if __name__=='__main__':main()
