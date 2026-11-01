from __future__ import annotations
import argparse, json, sys
from .coordinator import Coordinator
from .models import RuntimeErrorBase

def main(argv=None):
    p=argparse.ArgumentParser(prog='uneXpected-v7'); sub=p.add_subparsers(dest='cmd',required=True)
    sub.add_parser('status'); sub.add_parser('list')
    run=sub.add_parser('run'); run.add_argument('agent_id'); run.add_argument('--objective',required=True); run.add_argument('--inputs',default='{}'); run.add_argument('--idempotency-key'); run.add_argument('--deadline',type=float,default=30.0)\n    lifecycle=sub.add_parser('lifecycle'); lifecycle.add_argument('agent_id'); lifecycle.add_argument('--objective',required=True); lifecycle.add_argument('--inputs',default='{}'); lifecycle.add_argument('--max-corrections',type=int,default=1); lifecycle.add_argument('--deadline',type=float,default=60.0)
    chain=sub.add_parser('chain'); chain.add_argument('agents',nargs='+'); chain.add_argument('--objective',required=True); chain.add_argument('--inputs',default='{}'); chain.add_argument('--max-handoffs',type=int,default=4)
    graph=sub.add_parser('graph'); graph.add_argument('--graph-json',required=True); graph.add_argument('--max-nodes',type=int,default=20)
    sub.add_parser('eval')
    args=p.parse_args(argv); c=Coordinator(); exit_code=0
    try:
        if args.cmd=='status': out=c.status()
        elif args.cmd=='list': out={'count':len(c.registry),'agents':c.list_agents()}
        elif args.cmd=='run': out=c.invoke(args.agent_id,args.objective,json.loads(args.inputs),idempotency_key=args.idempotency_key,deadline_seconds=args.deadline).to_dict()\n        elif args.cmd=='lifecycle':\n            out=c.run_lifecycle(args.agent_id,args.objective,json.loads(args.inputs),max_corrections=args.max_corrections,deadline_seconds=args.deadline).to_dict()\n            exit_code=0 if out.get('status')=='delivered' and out.get('delivered') is True else 3
        elif args.cmd=='chain': out={'results':[r.to_dict() for r in c.run_chain(args.agents,args.objective,json.loads(args.inputs),max_handoffs=args.max_handoffs)]}
        elif args.cmd=='graph': out={'results':c.run_graph(json.loads(args.graph_json),max_nodes=args.max_nodes)}
        else:
            from .benchmark import BenchmarkRunner
            out=BenchmarkRunner().run().to_dict()
        print(json.dumps(out,indent=2,ensure_ascii=False)); return exit_code
    except Exception as e:
        print(json.dumps({'error':type(e).__name__,'message':str(e)}),file=sys.stderr); return 2
    finally: c.close()
if __name__=='__main__': raise SystemExit(main())
